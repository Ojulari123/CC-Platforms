import pytest
from app.services.datasets import seed_sample_datasets

CSV = b"name,age,city\nAlice,30,NYC\nBob,25,LA\nCarol,40,SF\n"

def _upload(client, content=CSV, filename="people.csv", name=None):
    data = {"name": name} if name is not None else {}
    return client.post("/datasets", files={"file": (filename, content, "text/csv")}, data=data)

def test_upload_csv_returns_columns_rowcount_and_owner(client, act_as):
    act_as(7)
    r = _upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["columns"] == ["name", "age", "city"]
    assert body["row_count"] == 3
    assert body["owner_user_id"] == 7
    assert body["is_sample"] is False
    assert body["original_filename"] == "people.csv"

def test_upload_defaults_name_to_filename(client, act_as):
    act_as(7)
    r = _upload(client, filename="mydata.csv")
    assert r.status_code == 201
    assert r.json()["name"] == "mydata.csv"

def test_upload_uses_provided_name(client, act_as):
    act_as(7)
    r = _upload(client, name="My Dataset")
    assert r.status_code == 201
    assert r.json()["name"] == "My Dataset"

def test_upload_rejects_undecodable_bytes(client, act_as):
    act_as(7)
    r = _upload(client, content=b"\xff\xfe\x00\x01not utf8")
    assert r.status_code == 400

def test_upload_rejects_empty_file(client, act_as):
    act_as(7)
    r = _upload(client, content=b"")
    assert r.status_code == 400

def test_upload_header_only_is_allowed_with_zero_rows(client, act_as):
    act_as(7)
    r = _upload(client, content=b"col_a,col_b\n")
    assert r.status_code == 201
    body = r.json()
    assert body["columns"] == ["col_a", "col_b"]
    assert body["row_count"] == 0

def test_upload_rejects_oversized_file(client, act_as):
    act_as(7)
    # One byte over the 5 MB default limit → 413.
    big = b"a,b\n" + b"x,y\n" * (5 * 1024 * 1024)
    r = _upload(client, content=big)
    assert r.status_code == 413

def test_upload_just_over_limit_is_413(client, act_as):
    from app.config import settings
    act_as(7)
    # Exactly one byte past the limit — the chunked read must abort with 413, not buffer the whole body.
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    over = b"x" * (limit + 1)
    r = _upload(client, content=over)
    assert r.status_code == 413

def test_upload_malformed_csv_is_400(client, act_as):
    act_as(7)
    # An unterminated quoted field grows past csv's field-size limit and raises csv.Error
    # It must be a 400, not an uncaught 500.
    content = b'a\n"' + b"x" * 200000
    r = _upload(client, content=content)
    assert r.status_code == 400
    assert "malformed csv" in r.json()["detail"].lower()

def test_list_returns_own_datasets_plus_samples(client, act_as, db):
    seed_sample_datasets(db)
    act_as(7)
    _upload(client, name="Mine")
    r = client.get("/datasets")
    assert r.status_code == 200
    body = r.json()
    names = {item["name"] for item in body["items"]}
    assert "Mine" in names
    assert "Iris (sample)" in names
    assert body["total"] == 3  # 2 samples + 1 upload

def test_second_user_sees_samples_but_not_others_private_data(client, act_as, db):
    seed_sample_datasets(db)
    act_as(7)
    _upload(client, name="User7 private")
    act_as(99)
    r = client.get("/datasets")
    body = r.json()
    names = {item["name"] for item in body["items"]}
    assert "User7 private" not in names
    assert "Iris (sample)" in names
    assert body["total"] == 2  # only the 2 samples

def test_summary_counts_owned_and_samples_separately(client, act_as, db):
    seed_sample_datasets(db)
    act_as(7)
    _upload(client, name="Mine A")
    _upload(client, name="Mine B")
    r = client.get("/datasets/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["owned_count"] == 2
    assert body["sample_count"] == 2
    assert {item["name"] for item in body["recent"]} == {"Mine A", "Mine B", "Iris (sample)", "Monthly Sales (sample)"}

def test_summary_excludes_other_users_datasets_from_owned_count(client, act_as, db):
    seed_sample_datasets(db)
    act_as(7)
    _upload(client, name="User7 private")
    act_as(99)
    body = client.get("/datasets/summary").json()
    assert body["owned_count"] == 0
    assert body["sample_count"] == 2
    assert "User7 private" not in {item["name"] for item in body["recent"]}

def test_summary_recent_is_capped_and_newest_first(client, act_as):
    act_as(7)
    for i in range(8):
        _upload(client, name=f"ds-{i}")
    body = client.get("/datasets/summary?recent=3").json()
    assert body["owned_count"] == 8
    assert [item["name"] for item in body["recent"]] == ["ds-7", "ds-6", "ds-5"]

def test_summary_counts_beyond_one_page_without_paging(client, act_as, db):
    seed_sample_datasets(db)
    act_as(7)
    for i in range(60):
        _upload(client, name=f"bulk-{i}")
    body = client.get("/datasets/summary?recent=0").json()
    assert body["owned_count"] == 60  # more than the 50-row default page
    assert body["sample_count"] == 2
    assert body["recent"] == []

def test_summary_recent_over_cap_is_422(client, act_as):
    act_as(7)
    assert client.get("/datasets/summary?recent=21").status_code == 422

def test_get_own_dataset_ok(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]
    r = client.get(f"/datasets/{ds_id}")
    assert r.status_code == 200
    assert r.json()["id"] == ds_id

def test_get_sample_ok_for_any_user(client, act_as, db):
    from app.models import Dataset
    from sqlalchemy import select
    seed_sample_datasets(db)
    sample_id = db.scalars(select(Dataset.id).where(Dataset.is_sample.is_(True))).first()
    act_as(12345)
    r = client.get(f"/datasets/{sample_id}")
    assert r.status_code == 200
    assert r.json()["is_sample"] is True

def test_get_someone_elses_private_is_forbidden(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]
    act_as(99)
    r = client.get(f"/datasets/{ds_id}")
    assert r.status_code == 403

def test_get_missing_is_404(client, act_as):
    act_as(7)
    r = client.get("/datasets/999999")
    assert r.status_code == 404

def test_preview_returns_first_n_rows_and_truncated_flag(client, act_as):
    act_as(7)
    # 12 data rows, preview 5 → truncated True.
    rows = "".join(f"{i},v{i}\n" for i in range(12))
    content = ("a,b\n" + rows).encode("utf-8")
    ds_id = _upload(client, content=content).json()["id"]
    r = client.get(f"/datasets/{ds_id}/preview?rows=5")
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["a", "b"]
    assert len(body["rows"]) == 5
    assert body["row_count"] == 12
    assert body["truncated"] is True

def test_preview_not_truncated_when_fewer_rows_than_limit(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]  # 3 data rows
    r = client.get(f"/datasets/{ds_id}/preview?rows=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 3
    assert body["truncated"] is False

def test_preview_rows_over_cap_is_422(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]
    r = client.get(f"/datasets/{ds_id}/preview?rows=501")
    assert r.status_code == 422

def test_preview_rows_at_cap_is_allowed(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]  # 3 data rows
    r = client.get(f"/datasets/{ds_id}/preview?rows=500")
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 3  # only 3 rows exist, cap just permits asking

def test_delete_owner_then_gone(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]
    r = client.delete(f"/datasets/{ds_id}")
    assert r.status_code == 204
    assert client.get(f"/datasets/{ds_id}").status_code == 404

def test_delete_non_owner_is_forbidden(client, act_as):
    act_as(7)
    ds_id = _upload(client).json()["id"]
    act_as(99)
    r = client.delete(f"/datasets/{ds_id}")
    assert r.status_code == 403

def test_delete_sample_is_forbidden(client, act_as, db):
    seed_sample_datasets(db)
    from app.models import Dataset
    from sqlalchemy import select
    sample_id = db.scalars(select(Dataset.id).where(Dataset.is_sample.is_(True))).first()
    act_as(7)
    r = client.delete(f"/datasets/{sample_id}")
    assert r.status_code == 403

def test_seeding_is_idempotent(client, act_as, db):
    from app.models import Dataset
    from sqlalchemy import func, select
    seed_sample_datasets(db)
    seed_sample_datasets(db)  # second call must be a no-op
    count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_sample.is_(True)))
    assert count == 2

def test_duplicate_sample_name_violates_partial_unique_index(db):
    # The uq_sample_name index forbids a second SAMPLE with the same name
    # This is what makes a concurrent double-seed lose instead of duplicating.
    from app.models import Dataset
    from sqlalchemy.exc import IntegrityError
    seed_sample_datasets(db)
    db.add(Dataset(
        owner_user_id=None, is_sample=True, name="Iris (sample)",
        original_filename="dup.csv", content="a\n1\n", columns='["a"]', row_count=1,
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

def test_partial_index_allows_duplicate_name_for_user_upload(db):
    # The predicate only covers samples, so a user upload may reuse a sample's name without tripping the index.
    from app.models import Dataset
    from sqlalchemy import func, select
    seed_sample_datasets(db)
    db.add(Dataset(
        owner_user_id=7, is_sample=False, name="Iris (sample)",
        original_filename="mine.csv", content="a\n1\n", columns='["a"]', row_count=1,
    ))
    db.flush()  # must not raise
    count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.name == "Iris (sample)"))
    assert count == 2

def test_seeded_samples_appear_for_a_fresh_user(client, act_as, db):
    seed_sample_datasets(db)
    act_as(4242)  # a user who has uploaded nothing
    r = client.get("/datasets")
    assert r.status_code == 200
    assert r.json()["total"] == 2

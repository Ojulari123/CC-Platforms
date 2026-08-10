from datetime import date, datetime, timezone
import pytest
from app.models import Commit, Issue, LlmUsage, PullRequest, Report, Repository
from app.services import generation, llm
from app.services.generation import _MAX_ITEMS_PER_KIND
from app.services.llm import LLMError, LLMResult
from app.services.prompts import PROMPT_VERSION

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
WEEK = "2026-07-20"  # a Monday

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
LEAD = dict(user_id=LEAD_ID, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])

FAKE = LLMResult(
    summary_manager="Shipped the auth refactor and reviewed two PRs.",
    summary_exec="Steady progress on auth.",
    next_week_goals="Finish the token rotation work.",
    model="gpt-4o-mini",
    token_count=321,
)

def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)

def _seed_repo(db, gh_id=1, name="alpha", dept_id=DEPT, lead=LEAD_ID, deputy=DEPUTY_ID):
    repo = Repository(
        github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name,
        dept_id=dept_id, lead_user_id=lead, deputy_user_id=deputy,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo

def _seed_week_activity(db, repo_id, user_id=10, commits=2, prs=1):
    for i in range(commits):
        db.add(Commit(repo_id=repo_id, sha=f"w{i}", author_user_id=user_id,
                      message=f"commit {i}", committed_at=_dt(2026, 7, 21 + i)))
    for i in range(prs):
        db.add(PullRequest(repo_id=repo_id, github_pr_id=100 + i, number=7 + i, title="pr",
                           state="open", merged=False, author_user_id=user_id, gh_created_at=_dt(2026, 7, 22)))
    db.commit()

@pytest.fixture
def mock_llm(monkeypatch):
    rec = {"calls": 0, "last_payload": None}

    def _fake(activity_payload):
        rec["calls"] += 1
        rec["last_payload"] = activity_payload
        return FAKE

    monkeypatch.setattr(llm, "generate_summaries", _fake)
    return rec

class TestGenerateHappyPath:
    def test_generates_a_draft_with_the_mocked_summaries(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["author_user_id"] == 10
        assert body["week_start"] == WEEK
        assert body["summary_manager"] == FAKE.summary_manager
        assert body["summary_exec"] == FAKE.summary_exec
        assert body["next_week_goals"] == FAKE.next_week_goals
        assert body["generated_at"] is not None
        assert "model_used" not in body
        assert "token_count" not in body
        assert mock_llm["calls"] == 1

    def test_generation_stamps_the_prompt_version(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text
        assert r.json()["prompt_version"] == PROMPT_VERSION
        assert db.get(Report, r.json()["id"]).prompt_version == PROMPT_VERSION

    def test_regenerating_restamps_the_prompt_version(self, client, act_as, db, mock_llm, monkeypatch):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        first = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK}).json()
        monkeypatch.setattr(generation, "PROMPT_VERSION", "2099-01-01.9")
        again = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK}).json()
        assert again["id"] == first["id"]
        assert again["prompt_version"] == "2099-01-01.9"

    def test_a_hand_written_report_has_no_prompt_version(self, client, act_as, db):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        r = client.post("/reports", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text
        assert r.json()["prompt_version"] is None
        assert client.get(f"/reports/{r.json()['id']}").json()["prompt_version"] is None

    def test_generation_records_llm_usage(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text
        usage = db.query(LlmUsage).all()
        assert len(usage) == 1
        assert usage[0].report_id == r.json()["id"]
        assert usage[0].user_id == 10
        assert usage[0].tokens == 321

    def test_report_and_usage_land_in_one_commit(self, client, act_as, db, mock_llm, monkeypatch):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)

        def _broken_ledger(**kwargs):
            raise RuntimeError("llm_usage insert failed")

        monkeypatch.setattr(generation, "LlmUsage", _broken_ledger)
        act_as(**ENGINEER)
        with pytest.raises(RuntimeError):
            client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})

        assert db.query(Report).count() == 0
        assert db.query(LlmUsage).count() == 0

    def test_sparse_activity_still_generates(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id, commits=1, prs=0)
        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text
        assert mock_llm["calls"] == 1

    def test_regenerating_overwrites_an_editable_draft(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        first = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK}).json()
        second = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert second.status_code == 201, second.text
        assert second.json()["id"] == first["id"]
        assert mock_llm["calls"] == 2

class TestTruncation:

    def test_item_lists_are_capped_but_counts_stay_exact(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        over = _MAX_ITEMS_PER_KIND + 5
        for i in range(over):
            db.add(Commit(repo_id=repo.id, sha=f"big{i}", author_user_id=10,
                          message=f"commit {i}", committed_at=_dt(2026, 7, 21)))
        db.commit()

        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 201, r.text

        payload = mock_llm["last_payload"]
        assert len(payload["commits"]) == _MAX_ITEMS_PER_KIND
        assert payload["counts"]["commits"] == over
        assert payload["truncated"] is True

class TestGenerateGuards:
    def test_empty_week_is_422_and_never_calls_the_llm(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        act_as(**LEAD)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 422, r.text
        assert mock_llm["calls"] == 0
        assert db.query(Report).count() == 0

    def test_llm_failure_returns_502_not_500(self, client, act_as, db, monkeypatch):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)

        def _boom(activity_payload):
            raise LLMError("provider down after retry")

        monkeypatch.setattr(llm, "generate_summaries", _boom)
        act_as(**ENGINEER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 502, r.text
        assert "unavailable" in r.json()["detail"].lower()
        assert db.query(Report).count() == 0

    def test_ineligible_user_is_403(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**OUTSIDER)
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 403, r.text
        assert mock_llm["calls"] == 0

    def test_regenerating_a_decided_report_is_409(self, client, act_as, db, mock_llm):
        repo = _seed_repo(db)
        _seed_week_activity(db, repo.id)
        act_as(**ENGINEER)
        rid = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK}).json()["id"]
        client.post(f"/reports/{rid}/submit")
        r = client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK})
        assert r.status_code == 409, r.text

    def test_requires_a_token(self, client, db):
        repo = _seed_repo(db)
        assert client.post("/reports/generate", json={"repo_id": repo.id, "week_start": WEEK}).status_code == 401

    def test_missing_repo_is_404(self, client, act_as, mock_llm):
        act_as(**ENGINEER)
        assert client.post("/reports/generate", json={"repo_id": 9999, "week_start": WEEK}).status_code == 404

from datetime import date, datetime, timedelta, timezone
import httpx
import pytest
from app.config import settings
from app.models import Commit, Repository
from app.services import identity_client

# Write access from activity is a rolling window off the clock, so the seed commit that
# makes these users contributors is relative: a fixed date ages out of the window.
RECENT = datetime.now(timezone.utc) - timedelta(days=1)

DEPT = 1
LEAD_ID = 20
DEPUTY_ID = 25
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
ENGINEER_2 = dict(user_id=11, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
LEAD = dict(user_id=LEAD_ID, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)

NAMES = {
    10: ("Ada", "Lovelace"),
    11: ("Grace", "Hopper"),
    20: ("Katherine", "Johnson"),
    25: ("Annie", "Easley"),
    99: ("Dorothy", "Vaughan"),
}


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_API_URL", "http://identity:8000")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_ID", "pulse")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "shh")
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    yield
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0


class FakeIdentity:

    def __init__(self, monkeypatch, *, profile_status=200, reverse=False, transport_error=False, known=None):
        self.calls = {"token": 0, "profiles": 0}
        self.batches = []
        self._status = profile_status
        self._reverse = reverse
        self._transport_error = transport_error
        self._known = NAMES if known is None else known
        monkeypatch.setattr(identity_client.httpx, "post", self._post)

    def reset(self):
        self.calls["profiles"] = 0
        self.batches.clear()
        identity_client.clear_profile_cache()

    def _post(self, url, **kwargs):
        if url.endswith("/oauth/token"):
            self.calls["token"] += 1
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        self.calls["profiles"] += 1
        if self._transport_error:
            raise httpx.ConnectError("identity unreachable")
        ids = kwargs["json"]["user_ids"]
        self.batches.append(ids)
        if self._status != 200:
            return httpx.Response(self._status, json={"detail": "nope"})
        rows = [
            {"user_id": uid, "first_name": self._known[uid][0], "last_name": self._known[uid][1],
             "avatar_url": None, "is_active": True}
            for uid in ids if uid in self._known
        ]
        if self._reverse:
            rows.reverse()
        return httpx.Response(200, json={"users": rows})


def _seed_repo(db, *, lead=LEAD_ID, deputy=DEPUTY_ID, contributors=(10, 11)):
    repo = Repository(github_repo_id=1, full_name="org/alpha", owner="org", name="alpha",
                      dept_id=DEPT, lead_user_id=lead, deputy_user_id=deputy)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    for uid in contributors:
        db.add(Commit(repo_id=repo.id, sha=f"a-{uid}", author_user_id=uid,
                      committed_at=RECENT))
    db.commit()
    return repo.id


def _monday():
    t = date.today()
    return t - timedelta(days=t.weekday())


def _draft(client, repo_id, week=None):
    return client.post("/reports", json={"repo_id": repo_id, "summary_manager": "did the work",
                                         "week_start": (week or _monday()).isoformat()}).json()["id"]


class TestReportNames:
    def test_get_report_carries_author_alongside_the_id(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        rid = _draft(client, repo_id)

        body = client.get(f"/reports/{rid}").json()
        assert body["author_user_id"] == 10
        assert body["author"] == {"user_id": 10, "first_name": "Ada", "last_name": "Lovelace",
                                  "avatar_url": None, "is_active": True}

    def test_list_resolves_every_author_in_one_call(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        _draft(client, repo_id)
        act_as(**ENGINEER_2)
        _draft(client, repo_id)
        fake.reset()

        act_as(**PLATFORM)
        items = client.get("/reports").json()["items"]
        assert {i["author_user_id"]: i["author"]["first_name"] for i in items} == {10: "Ada", 11: "Grace"}
        assert fake.calls["profiles"] == 1
        assert sorted(fake.batches[0]) == [10, 11]

    def test_names_land_by_user_id_when_identity_answers_out_of_order(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch, reverse=True)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        _draft(client, repo_id)
        act_as(**ENGINEER_2)
        _draft(client, repo_id)
        fake.reset()

        act_as(**PLATFORM)
        items = client.get("/reports").json()["items"]
        by_id = {i["author_user_id"]: i["author"] for i in items}
        assert by_id[10]["last_name"] == "Lovelace"
        assert by_id[11]["last_name"] == "Hopper"

    def test_unknown_author_leaves_the_name_absent(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch, known={11: NAMES[11]})
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        rid = _draft(client, repo_id)

        body = client.get(f"/reports/{rid}").json()
        assert body["author_user_id"] == 10
        assert body["author"] is None

    def test_approval_actor_and_comment_author_are_named(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        rid = _draft(client, repo_id)
        client.post(f"/reports/{rid}/submit")
        act_as(**LEAD)
        client.post(f"/reports/{rid}/approve", json={"note": "good"})
        comment = client.post(f"/reports/{rid}/comments", json={"body": "nice"}).json()
        assert comment["author"]["first_name"] == "Katherine"

        approvals = client.get(f"/reports/{rid}/approvals").json()["items"]
        actors = {a["actor_user_id"]: a["actor"]["first_name"] for a in approvals}
        assert actors == {10: "Ada", 20: "Katherine"}

        comments = client.get(f"/reports/{rid}/comments").json()["items"]
        assert comments[0]["author_user_id"] == 20 and comments[0]["author"]["last_name"] == "Johnson"


class TestActivityNames:
    def test_my_activity_carries_the_person_alongside_the_id(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch)
        _seed_repo(db)
        act_as(**ENGINEER)

        body = client.get("/activity/me").json()
        assert body["user_id"] == 10
        assert body["user"] == {"user_id": 10, "first_name": "Ada", "last_name": "Lovelace",
                                "avatar_url": None, "is_active": True}
        assert fake.calls["profiles"] == 1

    def test_another_engineers_activity_is_named(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch)
        _seed_repo(db)
        act_as(**PLATFORM)

        body = client.get("/activity/11").json()
        assert body["user_id"] == 11 and body["user"]["last_name"] == "Hopper"
        assert fake.calls["profiles"] == 1
        assert fake.batches[0] == [11]

    def test_unknown_user_leaves_the_name_absent(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch, known={})
        _seed_repo(db)
        act_as(**ENGINEER)

        body = client.get("/activity/me").json()
        assert body["user_id"] == 10 and body["user"] is None


class TestRepositoryNames:
    def test_lead_and_deputy_are_named_in_one_call(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db)
        act_as(**PLATFORM)

        body = client.get(f"/github/repositories/{repo_id}").json()
        assert body["lead_user_id"] == 20 and body["lead"]["first_name"] == "Katherine"
        assert body["deputy_user_id"] == 25 and body["deputy"]["last_name"] == "Easley"
        assert fake.calls["profiles"] == 1
        assert sorted(fake.batches[0]) == [20, 25]

    def test_unset_lead_and_deputy_stay_null_without_calling_identity(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db, lead=None, deputy=None)
        act_as(**PLATFORM)

        body = client.get(f"/github/repositories/{repo_id}").json()
        assert body["lead"] is None and body["deputy"] is None
        assert fake.calls["profiles"] == 0


class TestDegradation:
    def test_identity_unreachable_still_returns_the_report(self, client, act_as, db, monkeypatch):
        fake = FakeIdentity(monkeypatch, transport_error=True)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        rid = _draft(client, repo_id)

        r = client.get(f"/reports/{rid}")
        assert r.status_code == 200
        assert r.json()["author_user_id"] == 10 and r.json()["author"] is None
        assert fake.calls["profiles"] >= 1

    def test_identity_403_still_returns_the_list(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch, profile_status=403)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        _draft(client, repo_id)

        r = client.get("/reports")
        assert r.status_code == 200
        items = r.json()["items"]
        assert items[0]["author_user_id"] == 10 and items[0]["author"] is None

    def test_identity_500_still_returns_repositories(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch, profile_status=500)
        _seed_repo(db)
        act_as(**PLATFORM)

        r = client.get("/github/repositories")
        assert r.status_code == 200
        assert r.json()["items"][0]["lead"] is None

    def test_identity_unreachable_still_returns_activity(self, client, act_as, db, monkeypatch):
        FakeIdentity(monkeypatch, transport_error=True)
        _seed_repo(db)
        act_as(**ENGINEER)

        r = client.get("/activity/me")
        assert r.status_code == 200
        assert r.json()["user_id"] == 10 and r.json()["user"] is None
        assert r.json()["counts"]["commits"] == 1

    def test_unconfigured_secret_never_calls_identity(self, client, act_as, db, monkeypatch):
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        fake = FakeIdentity(monkeypatch)
        repo_id = _seed_repo(db)
        act_as(**ENGINEER)
        rid = _draft(client, repo_id)

        assert client.get(f"/reports/{rid}").json()["author"] is None
        assert fake.calls == {"token": 0, "profiles": 0}


def test_cached_profile_serves_the_next_request_without_a_second_call(client, act_as, db, monkeypatch):
    fake = FakeIdentity(monkeypatch)
    repo_id = _seed_repo(db)
    act_as(**ENGINEER)
    rid = _draft(client, repo_id)
    fake.reset()

    assert client.get(f"/reports/{rid}").json()["author"]["first_name"] == "Ada"
    assert client.get(f"/reports/{rid}").json()["author"]["first_name"] == "Ada"
    assert fake.calls["profiles"] == 1

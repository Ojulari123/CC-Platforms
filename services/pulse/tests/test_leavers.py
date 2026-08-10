from datetime import datetime, timezone
import httpx
import pytest
from sqlalchemy import select
from app import crypto
from app.config import settings
from app.models import Commit, GitHubAccount, Issue, PullRequest, Repository, Review, SyncRun
from app.services import identity_client
from app.services import sync as sync_service
from app.services.leavers import revoke_departed_credentials

TOKEN_URL = "http://identity:8000/oauth/token"
PROFILES_URL = "http://identity:8000/internal/users/profiles"


@pytest.fixture(autouse=True)
def _wired_to_identity(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_API_URL", "http://identity:8000")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "shh")
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    identity_client.clear_profile_cache()
    yield
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    identity_client.clear_profile_cache()


def _identity_says(monkeypatch, profiles_response, unknown=()):
    def _post(url, **kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        assert url == PROFILES_URL
        if callable(profiles_response):
            return profiles_response(url, kwargs)
        return httpx.Response(200, json={"users": profiles_response, "unknown_user_ids": list(unknown)})
    monkeypatch.setattr(identity_client.httpx, "post", _post)


def _profile(uid, active):
    return {"user_id": uid, "first_name": "F", "last_name": "L", "avatar_url": None, "is_active": active}


def _connect(db, user_id, login, github_user_id):
    db.add(GitHubAccount(user_id=user_id, github_user_id=github_user_id, github_login=login,
                         access_token_encrypted=crypto.encrypt(f"gho_{login}")))
    db.commit()


def _user_ids_with_credentials(db):
    return sorted(db.scalars(select(GitHubAccount.user_id)))


def test_an_inactive_users_credentials_are_dropped(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _connect(db, 11, "bob", 992)
    _identity_says(monkeypatch, [_profile(10, False), _profile(11, True)])

    assert revoke_departed_credentials(db) == [10]
    assert _user_ids_with_credentials(db) == [11]


def test_everyone_active_changes_nothing(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _identity_says(monkeypatch, [_profile(10, True)])

    assert revoke_departed_credentials(db) == []
    assert _user_ids_with_credentials(db) == [10]


def test_a_hard_deleted_users_credentials_are_dropped(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _connect(db, 11, "bob", 992)
    _identity_says(monkeypatch, [_profile(11, True)], unknown=[10])

    assert revoke_departed_credentials(db) == [10]
    assert _user_ids_with_credentials(db) == [11]


def test_deactivated_and_deleted_go_in_the_same_pass(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _connect(db, 11, "bob", 992)
    _connect(db, 12, "cat", 993)
    _identity_says(monkeypatch, [_profile(11, False), _profile(12, True)], unknown=[10])

    assert revoke_departed_credentials(db) == [10, 11]
    assert _user_ids_with_credentials(db) == [12]


class TestIdentityBeingUnreachableDeletesNothing:

    def test_connection_refused(self, db, monkeypatch):
        _connect(db, 10, "ada", 991)
        _connect(db, 11, "bob", 992)

        def _post(url, **kwargs):
            raise httpx.ConnectError("identity unreachable")
        monkeypatch.setattr(identity_client.httpx, "post", _post)

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == [10, 11]

    def test_identity_returns_500(self, db, monkeypatch):
        _connect(db, 10, "ada", 991)
        _identity_says(monkeypatch, lambda url, kwargs: httpx.Response(500, json={"detail": "boom"}))

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == [10]

    def test_scope_not_granted_yet(self, db, monkeypatch):
        _connect(db, 10, "ada", 991)
        _identity_says(monkeypatch, lambda url, kwargs: httpx.Response(403, json={"detail": "scope"}))

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == [10]

    def test_unconfigured_service_client(self, db, monkeypatch):
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        _connect(db, 10, "ada", 991)

        def _post(url, **kwargs):
            raise AssertionError("should not call identity when unconfigured")
        monkeypatch.setattr(identity_client.httpx, "post", _post)

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == [10]

    def test_the_skip_is_logged_so_it_is_not_silent(self, db, monkeypatch, caplog):
        _connect(db, 10, "ada", 991)

        def _post(url, **kwargs):
            raise httpx.ConnectError("identity unreachable")
        monkeypatch.setattr(identity_client.httpx, "post", _post)

        with caplog.at_level("WARNING", logger="app.services.leavers"):
            revoke_departed_credentials(db)
        assert "leaver check skipped" in caplog.text

    def test_identity_answers_about_someone_else_only(self, db, monkeypatch):
        _connect(db, 10, "ada", 991)
        _connect(db, 11, "bob", 992)
        _identity_says(monkeypatch, [_profile(11, True)])

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == [10, 11]

    def test_a_chunk_identity_failed_on_is_not_read_as_deleted(self, db, monkeypatch):
        for uid in range(1, 251):
            _connect(db, uid, f"u{uid}", 900 + uid)
        calls = {"n": 0}

        def _profiles(url, kwargs):
            calls["n"] += 1
            ids = kwargs["json"]["user_ids"]
            if calls["n"] == 1:
                return httpx.Response(200, json={"users": [_profile(i, True) for i in ids],
                                                 "unknown_user_ids": []})
            return httpx.Response(500, json={"detail": "boom"})

        _identity_says(monkeypatch, _profiles)

        assert revoke_departed_credentials(db) == []
        assert _user_ids_with_credentials(db) == list(range(1, 251))

    def test_a_failed_chunk_does_not_bury_the_leaver_in_the_chunk_that_answered(self, db, monkeypatch):
        for uid in range(1, 251):
            _connect(db, uid, f"u{uid}", 900 + uid)
        calls = {"n": 0}

        def _profiles(url, kwargs):
            calls["n"] += 1
            ids = kwargs["json"]["user_ids"]
            if calls["n"] == 1:
                return httpx.Response(200, json={"users": [_profile(i, True) for i in ids if i != 7],
                                                 "unknown_user_ids": [7]})
            return httpx.Response(500, json={"detail": "boom"})

        _identity_says(monkeypatch, _profiles)

        assert revoke_departed_credentials(db) == [7]
        assert _user_ids_with_credentials(db) == [uid for uid in range(1, 251) if uid != 7]


def test_no_connected_accounts_never_calls_identity(db, monkeypatch):
    def _post(url, **kwargs):
        raise AssertionError("should not ask identity about nobody")
    monkeypatch.setattr(identity_client.httpx, "post", _post)

    assert revoke_departed_credentials(db) == []


def _history_for(db, user_id):
    repo = Repository(github_repo_id=555, full_name="org/alpha", owner="org", name="alpha", dept_id=1)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    db.add(Commit(repo_id=repo.id, sha="abc", author_user_id=user_id, author_github_login="ada",
                  message="did work", committed_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc)))
    pr = PullRequest(repo_id=repo.id, github_pr_id=1, number=7, title="a PR", state="open",
                     author_user_id=user_id, author_github_login="ada")
    db.add(pr)
    db.add(Issue(repo_id=repo.id, github_issue_id=22, number=3, title="a bug", state="open",
                 author_user_id=user_id, author_github_login="ada"))
    db.commit()
    db.refresh(pr)
    db.add(Review(pull_request_id=pr.id, github_review_id=11, reviewer_user_id=user_id,
                  reviewer_github_login="ada", state="approved"))
    db.commit()
    return repo


def _attributed(db, user_id):
    return {
        "commits": db.scalars(select(Commit).where(Commit.author_user_id == user_id)).all(),
        "pull_requests": db.scalars(select(PullRequest).where(PullRequest.author_user_id == user_id)).all(),
        "reviews": db.scalars(select(Review).where(Review.reviewer_user_id == user_id)).all(),
        "issues": db.scalars(select(Issue).where(Issue.author_user_id == user_id)).all(),
    }


def test_history_survives_the_credential_being_dropped(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _history_for(db, 10)
    _identity_says(monkeypatch, [_profile(10, False)])

    assert revoke_departed_credentials(db) == [10]

    assert _user_ids_with_credentials(db) == []
    still_there = _attributed(db, 10)
    assert [len(v) for v in still_there.values()] == [1, 1, 1, 1], still_there
    assert still_there["commits"][0].sha == "abc"
    assert still_there["commits"][0].author_github_login == "ada"


def test_history_survives_a_hard_deleted_user_too(db, monkeypatch):
    _connect(db, 10, "ada", 991)
    _history_for(db, 10)
    _identity_says(monkeypatch, [], unknown=[10])

    assert revoke_departed_credentials(db) == [10]

    assert _user_ids_with_credentials(db) == []
    still_there = _attributed(db, 10)
    assert [len(v) for v in still_there.values()] == [1, 1, 1, 1], still_there
    assert still_there["commits"][0].sha == "abc"
    assert still_there["commits"][0].author_github_login == "ada"
    assert still_there["reviews"][0].reviewer_user_id == 10


class TestTheSyncPassIsWhereItHappens:
    def test_a_departed_users_token_is_gone_before_github_is_called(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect(db, 10, "ada", 991)
        _connect(db, 11, "bob", 992)
        _identity_says(monkeypatch, [_profile(10, False), _profile(11, True)])
        used = []

        class _Fake:
            def get_repo(self, full_name):
                return {"id": 555, "name": "alpha", "full_name": "org/alpha", "private": False,
                        "default_branch": "main", "owner": {"login": "org"}}
            def list_commits(self, full_name, since=None):
                return []
            def list_pull_requests(self, full_name, since=None):
                return []
            def list_issues(self, full_name, since=None):
                return []
            def close(self):
                pass

        def _make(token):
            used.append(token)
            return _Fake()

        runs = sync_service.run_full_sync(db, make_client=_make)

        assert used == ["gho_bob"]
        assert _user_ids_with_credentials(db) == [11]
        assert "departed user(s): 10" in runs[0].detail
        assert runs[0].repo_id is None

    def test_nothing_is_recorded_when_nobody_left(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "")
        _connect(db, 10, "ada", 991)
        _identity_says(monkeypatch, [_profile(10, True)])

        runs = sync_service.run_full_sync(db)

        assert [r.detail for r in runs] == ["no repos configured (set GITHUB_REPOS)"]
        assert db.scalar(select(SyncRun).where(SyncRun.detail.like("%departed%"))) is None

    def test_a_later_sync_does_not_erase_the_leavers_attribution(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect(db, 10, "ada", 991)
        _connect(db, 11, "bob", 992)
        _history_for(db, 10)
        _identity_says(monkeypatch, [_profile(10, False), _profile(11, True)])

        class _Fake:
            def get_repo(self, full_name):
                return {"id": 555, "name": "alpha", "full_name": "org/alpha", "private": False,
                        "default_branch": "main", "owner": {"login": "org"}}
            def list_commits(self, full_name, since=None):
                return [{"sha": "abc", "html_url": "u", "author": {"login": "ada"},
                         "commit": {"message": "did work", "committer": {"date": "2026-07-21T12:00:00Z"}}}]
            def list_pull_requests(self, full_name, since=None):
                return [{"id": 1, "number": 7, "title": "a PR", "state": "open", "merged_at": None,
                         "created_at": "2026-07-19T10:00:00Z", "updated_at": "2026-07-25T10:00:00Z",
                         "user": {"login": "ada"}, "html_url": "u"}]
            def list_reviews(self, full_name, number):
                return [{"id": 11, "user": {"login": "ada"}, "state": "APPROVED",
                         "submitted_at": "2026-07-21T11:00:00Z", "html_url": "u"}]
            def list_issues(self, full_name, since=None):
                return [{"id": 22, "number": 3, "title": "a bug", "state": "open",
                         "created_at": "2026-07-18T09:00:00Z", "closed_at": None,
                         "user": {"login": "ada"}, "html_url": "u"}]
            def close(self):
                pass

        sync_service.run_full_sync(db, make_client=lambda token: _Fake())

        db.expire_all()
        still_there = _attributed(db, 10)
        assert [len(v) for v in still_there.values()] == [1, 1, 1, 1], still_there

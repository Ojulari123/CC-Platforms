import logging
import time
import httpx
from sqlalchemy import func, select
from app import crypto
from app.celery_app import celery
from app.config import settings
from app.models import Commit, GitHubAccount, Issue, PullRequest, Repository, Review, SyncRun
from app.services import sync as sync_service
from app.services.github_client import GitHubClient
from app.services.repo_index import RECONNECT_DETAIL
import app.tasks  # noqa: F401 — registers the celery tasks asserted on below

REPO = {"id": 555, "name": "alpha", "full_name": "org/alpha", "private": False, "default_branch": "main", "owner": {"login": "org"}}

class FakeGitHub:

    def __init__(self, repo=REPO, commits=(), prs=(), reviews=None, issues=()):
        self._repo = repo
        self._commits = list(commits)
        self._prs = list(prs)
        self._reviews = reviews or {}
        self._issues = list(issues)
        self.commit_since = []
        self.pr_since = []

    def get_repo(self, full_name):
        return self._repo

    def list_branches(self, full_name):
        return []

    def list_commits(self, full_name, since=None, sha=None):
        self.commit_since.append(since)
        return self._commits

    def list_pull_requests(self, full_name, since=None):
        self.pr_since.append(since)
        return self._prs

    def list_reviews(self, full_name, number):
        return self._reviews.get(number, [])

    def list_issues(self, full_name, since=None):
        return self._issues

    def close(self):
        pass

def _connect_account(db, login="ada", user_id=10):
    db.add(GitHubAccount(user_id=user_id, github_user_id=99, github_login=login,
                         access_token_encrypted=crypto.encrypt("gho_token")))
    db.commit()

def _rich_fake():
    return FakeGitHub(
        commits=[{"sha": "abc", "html_url": "u", "author": {"login": "ada"},
                  "commit": {"message": "did work", "committer": {"date": "2026-07-20T10:00:00Z"}}}],
        prs=[{"id": 1, "number": 7, "title": "a PR", "state": "open", "merged_at": None,
              "created_at": "2026-07-19T10:00:00Z", "updated_at": "2026-07-20T10:00:00Z",
              "user": {"login": "ada"}, "html_url": "u"}],
        reviews={7: [{"id": 11, "user": {"login": "bob"}, "state": "APPROVED",
                      "submitted_at": "2026-07-20T11:00:00Z", "html_url": "u"}]},
        issues=[
            {"id": 22, "number": 3, "title": "a bug", "state": "open", "created_at": "2026-07-18T09:00:00Z",
             "closed_at": None, "user": {"login": "ada"}, "html_url": "u"},
            {"id": 23, "number": 8, "pull_request": {"url": "..."}, "title": "PR as issue",
             "state": "open", "user": {"login": "ada"}},
        ],
    )

def test_sync_pulls_and_attributes_activity(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    fake = _rich_fake()

    runs = sync_service.run_full_sync(db, make_client=lambda token: fake)

    assert len(runs) == 1 and runs[0].status == "success", runs[0].detail
    repo = db.scalar(select(Repository).where(Repository.github_repo_id == 555))
    assert repo is not None and repo.last_synced_at is not None
    assert runs[0].repo_id == repo.id

    commit = db.scalar(select(Commit))
    assert commit.sha == "abc" and commit.author_user_id == 10

    pr = db.scalar(select(PullRequest))
    assert pr.number == 7 and pr.author_user_id == 10

    review = db.scalar(select(Review))
    assert review.state == "approved" and review.reviewer_user_id is None

    issues = db.scalars(select(Issue)).all()
    assert len(issues) == 1 and issues[0].number == 3

def test_resync_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    sync_service.run_full_sync(db, make_client=lambda t: _rich_fake())
    sync_service.run_full_sync(db, make_client=lambda t: _rich_fake())
    assert db.scalar(select(func.count()).select_from(Commit)) == 1
    assert db.scalar(select(func.count()).select_from(PullRequest)) == 1
    assert db.scalar(select(func.count()).select_from(Review)) == 1

def test_second_run_is_incremental(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    fake = _rich_fake()
    sync_service.run_full_sync(db, make_client=lambda t: fake)
    sync_service.run_full_sync(db, make_client=lambda t: fake)
    assert fake.commit_since[0] is None
    assert fake.commit_since[1] is not None
    assert fake.pr_since[0] is None
    assert fake.pr_since[1] is not None

def test_untracked_repo_is_skipped(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    fake = _rich_fake()
    sync_service.run_full_sync(db, make_client=lambda t: fake)

    repo = db.scalar(select(Repository).where(Repository.full_name == "org/alpha"))
    repo.is_tracked = False
    db.commit()
    synced_at = repo.last_synced_at
    calls_before = len(fake.commit_since)
    commits_before = db.scalar(select(func.count()).select_from(Commit))
    built = []

    def _make(token):
        built.append(token)
        return fake

    runs = sync_service.run_full_sync(db, make_client=_make)

    assert len(runs) == 1 and runs[0].status == "skipped"
    assert runs[0].repo_id == repo.id and "not tracked" in runs[0].detail
    assert built == []
    assert len(fake.commit_since) == calls_before
    assert db.scalar(select(func.count()).select_from(Commit)) == commits_before
    db.refresh(repo)
    assert repo.last_synced_at == synced_at

def test_retracked_repo_syncs_again(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    fake = _rich_fake()
    sync_service.run_full_sync(db, make_client=lambda t: fake)
    repo = db.scalar(select(Repository).where(Repository.full_name == "org/alpha"))
    repo.is_tracked = False
    db.commit()
    sync_service.run_full_sync(db, make_client=lambda t: fake)
    repo.is_tracked = True
    db.commit()

    runs = sync_service.run_full_sync(db, make_client=lambda t: fake)
    assert runs[0].status == "success", runs[0].detail

def test_a_repo_never_synced_before_is_not_treated_as_untracked(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    runs = sync_service.run_full_sync(db, make_client=lambda t: _rich_fake())
    assert runs[0].status == "success", runs[0].detail

def test_no_repos_configured_records_a_no_op(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "")
    with caplog.at_level(logging.WARNING, logger="app.services.sync"):
        runs = sync_service.run_full_sync(db)
    assert len(runs) == 1 and runs[0].status == "success"
    assert runs[0].detail == "no repositories are configured to sync"
    # The variable an operator has to set is the operator's business: log, not `detail`.
    assert "GITHUB_REPOS" not in runs[0].detail
    assert "GITHUB_REPOS" in caplog.text

class _Exploding:
    """Raises the kind of message a driver or HTTP library raises: hosts, credentials,
    internal paths."""
    BOOM = "connection to postgresql://admin:hunter2@pulse-db.internal:5432/pulse failed"

    def __init__(self, at="get_repo"):
        self._at = at

    def get_repo(self, full_name):
        if self._at == "get_repo":
            raise RuntimeError(self.BOOM)
        return REPO

    def list_branches(self, full_name):
        return []

    def list_commits(self, full_name, since=None, sha=None):
        raise RuntimeError(self.BOOM)

    def close(self):
        pass

def test_a_failed_sync_keeps_the_exception_out_of_the_stored_detail(db, monkeypatch, caplog):
    """`detail` is persisted and served over the API, so it carries the repo, the stage
    and the run to look up. The exception itself belongs to the log."""
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)

    with caplog.at_level(logging.ERROR, logger="app.services.sync"):
        runs = sync_service.run_full_sync(db, make_client=lambda t: _Exploding())

    run = runs[0]
    assert run.status == "error"
    assert "hunter2" not in run.detail and "postgresql" not in run.detail
    assert run.detail == f"org/alpha: failed while connecting to GitHub; see the service log for sync run {run.id}"
    assert _Exploding.BOOM in caplog.text
    assert "org/alpha" in caplog.text and f"sync_run id={run.id}" in caplog.text

def test_a_failed_sync_records_which_stage_it_reached(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)

    with caplog.at_level(logging.ERROR, logger="app.services.sync"):
        runs = sync_service.run_full_sync(db, make_client=lambda t: _Exploding(at="list_commits"))

    assert runs[0].detail.startswith("org/alpha: failed while reading repository activity;")
    assert "reading repository activity" in caplog.text

def test_a_failed_syncs_detail_is_safe_to_serve(client, act_as, db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    sync_service.run_full_sync(db, make_client=lambda t: _Exploding())

    act_as(user_id=99, memberships=[], is_platform_admin=True)
    r = client.get("/github/sync-runs")

    assert r.status_code == 200
    body = r.text
    assert "hunter2" not in body and "pulse-db.internal" not in body
    served = [i for i in r.json()["items"] if i["status"] == "error"]
    assert served and all("failed while connecting to GitHub" in i["detail"] for i in served)

def test_an_inline_sync_without_the_encryption_key_is_a_handled_503(client, act_as, db, monkeypatch, caplog):
    """The stored token can't be decrypted without the key. That is a server configuration
    problem, and the app-level handler answers it as one rather than letting a 500 out."""
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)
    monkeypatch.setattr(settings, "GITHUB_TOKEN_ENC_KEY", "")
    act_as(user_id=99, memberships=[], is_platform_admin=True)

    with caplog.at_level(logging.ERROR, logger="app.crypto"):
        r = client.post("/github/sync?wait=true")

    assert r.status_code == 503, r.text
    assert "GITHUB_TOKEN_ENC_KEY" not in r.text and "Fernet" not in r.text
    assert r.json()["detail"] == "GitHub is not set up on this server. Contact an admin."
    assert "GITHUB_TOKEN_ENC_KEY" in caplog.text

def test_no_connected_account_is_an_error(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    runs = sync_service.run_full_sync(db, make_client=lambda t: FakeGitHub())
    assert runs[0].status == "error" and "no connected" in runs[0].detail

def test_client_waits_out_a_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()))}, json=[])
        return httpx.Response(200, json=[{"sha": "x"}])

    slept: list = []
    client = GitHubClient("tok", base_url="https://api.github.test", sleep=slept.append, transport=httpx.MockTransport(handler))
    out = client.list_commits("org/alpha")

    assert out == [{"sha": "x"}]
    assert calls["n"] == 2
    assert len(slept) == 1

def test_client_follows_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"sha": "b"}])
        nxt = str(request.url.copy_merge_params({"page": "2"}))
        return httpx.Response(200, json=[{"sha": "a"}], headers={"Link": f'<{nxt}>; rel="next"'})

    client = GitHubClient("tok", base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    assert client.list_commits("org/alpha") == [{"sha": "a"}, {"sha": "b"}]

def test_client_handles_a_secondary_rate_limit():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, headers={"Retry-After": "0", "X-RateLimit-Remaining": "42"}, json=[])
        return httpx.Response(200, json=[{"sha": "x"}])

    slept: list = []
    client = GitHubClient("tok", base_url="https://api.github.test", sleep=slept.append, transport=httpx.MockTransport(handler))
    assert client.list_commits("org/alpha") == [{"sha": "x"}]
    assert calls["n"] == 2 and len(slept) == 1

def test_client_pull_requests_stop_at_since():
    from datetime import datetime, timezone
    pages = [
        [{"number": 3, "updated_at": "2026-07-20T10:00:00Z"}, {"number": 2, "updated_at": "2026-07-01T10:00:00Z"}],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[0])

    client = GitHubClient("tok", base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    out = client.list_pull_requests("org/alpha", since=datetime(2026, 7, 10, tzinfo=timezone.utc))
    assert [p["number"] for p in out] == [3]

def test_sync_falls_back_to_a_second_account(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    db.add(GitHubAccount(user_id=10, github_user_id=1, github_login="ada", access_token_encrypted=crypto.encrypt("tok-A")))
    db.add(GitHubAccount(user_id=11, github_user_id=2, github_login="bob", access_token_encrypted=crypto.encrypt("tok-B")))
    db.commit()

    class NoAccess:
        def get_repo(self, full_name):
            req = httpx.Request("GET", "https://api.github.test")
            raise httpx.HTTPStatusError("forbidden", request=req, response=httpx.Response(403, request=req))

        def close(self):
            pass

    good = _rich_fake()
    runs = sync_service.run_full_sync(db, make_client=lambda token: good if token == "tok-B" else NoAccess())
    assert runs[0].status == "success", runs[0].detail
    assert db.scalar(select(Commit)) is not None

def test_sync_trigger_requires_admin(client, act_as, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "")
    act_as(user_id=10, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
    assert client.post("/github/sync?wait=true").status_code == 403

def test_sync_trigger_rejects_a_department_admin(client, act_as, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "")
    act_as(user_id=30, memberships=[{"dept_id": 1, "team_id": None, "role": "admin"}])
    assert client.post("/github/sync?wait=true").status_code == 403

def test_sync_trigger_inline_returns_results(client, act_as, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "")
    act_as(user_id=99, memberships=[], is_platform_admin=True)
    r = client.post("/github/sync?wait=true")
    assert r.status_code == 200 and r.json()["mode"] == "inline"

def test_sync_trigger_enqueues_by_default(client, act_as, monkeypatch):
    import app.routes.github as gh

    class FakeTask:
        id = "task-123"

    monkeypatch.setattr(gh.sync_all_repos, "delay", lambda: FakeTask())
    act_as(user_id=99, memberships=[], is_platform_admin=True)
    r = client.post("/github/sync")
    assert r.status_code == 200 and r.json() == {"mode": "queued", "task_id": "task-123"}

class TestSyncRunHistory:

    DEPT = 1
    ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
    OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])
    PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)

    def _seed(self, db, dept_id=DEPT, gh_id=1, name="alpha"):
        repo = Repository(github_repo_id=gh_id, full_name=f"org/{name}", owner="org", name=name, dept_id=dept_id)
        db.add(repo)
        db.commit()
        db.refresh(repo)
        return repo

    def _run(self, db, repo, status="success", detail="org/alpha: commits=3"):
        run = SyncRun(repo_id=repo.id if repo else None, status=status, detail=detail)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def test_requires_auth(self, client):
        assert client.get("/github/sync-runs").status_code == 401

    def test_returns_history_with_enough_to_explain_staleness(self, client, act_as, db):
        repo = self._seed(db)
        self._run(db, repo, status="rate_limited", detail="org/alpha: resumes at 12:30")
        act_as(**self.ENGINEER)

        body = client.get("/github/sync-runs").json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["status"] == "rate_limited"
        assert "resumes at 12:30" in item["detail"]
        assert item["repo_full_name"] == "org/alpha"
        assert item["started_at"] is not None

    def test_a_user_outside_the_repos_scope_sees_nothing(self, client, act_as, db):
        repo = self._seed(db)
        self._run(db, repo)
        act_as(**self.OUTSIDER)
        body = client.get("/github/sync-runs").json()
        assert body["total"] == 0 and body["items"] == []

    def test_filtering_by_repo_id_does_not_bypass_the_scope(self, client, act_as, db):
        repo = self._seed(db)
        self._run(db, repo)
        act_as(**self.OUTSIDER)
        assert client.get(f"/github/sync-runs?repo_id={repo.id}").json()["total"] == 0

    def test_repo_less_rows_are_platform_admin_only(self, client, act_as, db):
        self._run(db, None, status="error", detail="no connected GitHub account to sync with")
        act_as(**self.ENGINEER)
        assert client.get("/github/sync-runs").json()["total"] == 0
        act_as(**self.PLATFORM)
        assert client.get("/github/sync-runs").json()["total"] == 1

    def test_newest_first_and_paged(self, client, act_as, db):
        repo = self._seed(db)
        for i in range(3):
            self._run(db, repo, detail=f"run {i}")
        act_as(**self.ENGINEER)
        body = client.get("/github/sync-runs?limit=2&offset=0").json()
        assert body["total"] == 3 and body["limit"] == 2
        assert [i["detail"] for i in body["items"]] == ["run 2", "run 1"]

    def test_a_skipped_run_is_visible(self, client, act_as, db):
        repo = self._seed(db)
        self._run(db, repo, status="skipped", detail="org/alpha: not tracked")
        act_as(**self.ENGINEER)
        assert client.get("/github/sync-runs").json()["items"][0]["status"] == "skipped"


def test_daily_sync_is_registered_on_the_celery_app():
    assert "app.tasks.sync_all_repos" in celery.tasks
    assert "daily-github-sync" in celery.conf.beat_schedule
    assert celery.conf.beat_schedule["daily-github-sync"]["task"] == "app.tasks.sync_all_repos"


class TestCommitAttribution:
    """GitHub sends `author` and `committer` on a commit and they are different people
    after a squash merge: the author wrote the change, the committer pressed the button.
    Reading the wrong one puts one person's work under another's name."""

    def test_the_author_is_credited_not_the_committer(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db, login="ada", user_id=10)
        db.add(GitHubAccount(user_id=11, github_user_id=100, github_login="merger",
                             access_token_encrypted=crypto.encrypt("gho_token")))
        db.commit()
        fake = FakeGitHub(commits=[{
            "sha": "sq1", "html_url": "u",
            "author": {"login": "ada"},
            "committer": {"login": "merger"},
            "commit": {"message": "add parser (#42)", "committer": {"date": "2026-07-20T10:00:00Z"}},
        }])

        sync_service.run_full_sync(db, make_client=lambda token: fake)

        commit = db.scalar(select(Commit))
        assert commit.author_github_login == "ada"
        assert commit.author_user_id == 10

    def test_a_commit_github_cannot_match_is_left_unattributed(self, db, monkeypatch):
        """No fallback to the committer on purpose: unattributed is honest, crediting
        whoever merged is not."""
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db, login="merger", user_id=11)
        fake = FakeGitHub(commits=[{
            "sha": "x1", "html_url": "u",
            "author": None,
            "committer": {"login": "merger"},
            "commit": {"message": "vendored change", "committer": {"date": "2026-07-20T10:00:00Z"}},
        }])

        sync_service.run_full_sync(db, make_client=lambda token: fake)

        commit = db.scalar(select(Commit))
        assert commit.author_github_login is None
        assert commit.author_user_id is None

    def test_commit_author_login_reads_author_only(self):
        payload = {"author": {"login": "ada"}, "committer": {"login": "merger"}}
        assert sync_service.commit_author_login(payload) == "ada"
        assert sync_service.commit_author_login({"committer": {"login": "merger"}}) is None
        assert sync_service.commit_author_login({"author": None}) is None


class TestCollapseCommits:

    def _c(self, sha, message):
        return {"sha": sha, "message": message}

    def test_a_squash_and_the_branch_commit_it_absorbed_count_once(self):
        kept, merges, duplicates = sync_service.collapse_commits([
            self._c("sq", "add parser (#42)"),
            self._c("br", "add parser"),
        ])
        assert [c["sha"] for c in kept] == ["sq"]
        assert (merges, duplicates) == (0, 1)

    def test_a_merge_commit_is_not_somebody_elses_change(self):
        kept, merges, duplicates = sync_service.collapse_commits([
            self._c("m1", "Merge pull request #42 from org/feature"),
            self._c("m2", "Merge branch 'main' into feature"),
            self._c("w", "real work"),
        ])
        assert [c["sha"] for c in kept] == ["w"]
        assert (merges, duplicates) == (2, 0)

    def test_different_changes_are_left_alone(self):
        kept, merges, duplicates = sync_service.collapse_commits([
            self._c("a", "add parser"), self._c("b", "fix parser"), self._c("c", "document parser"),
        ])
        assert len(kept) == 3 and (merges, duplicates) == (0, 0)

    def test_only_the_subject_line_is_compared(self):
        kept, _, duplicates = sync_service.collapse_commits([
            self._c("sq", "add parser (#42)\n\n* first step\n* second step"),
            self._c("br", "add parser"),
        ])
        assert [c["sha"] for c in kept] == ["sq"] and duplicates == 1

    def test_empty_messages_are_kept_rather_than_collapsed(self):
        kept, _, duplicates = sync_service.collapse_commits([self._c("a", ""), self._c("b", None)])
        assert len(kept) == 2 and duplicates == 0

    def test_the_note_names_both_reasons_and_is_absent_when_nothing_changed(self):
        assert sync_service.collapse_note(0, 0) is None
        note = sync_service.collapse_note(1, 2)
        assert "1 merge commit(s) were left out" in note
        assert "2 commit(s) were counted once rather than twice" in note


class TestUnreadableRepo:

    def test_a_repo_no_account_can_open_says_to_reconnect(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/private")
        _connect_account(db)

        class Denied:
            def get_repo(self, full_name):
                raise httpx.HTTPStatusError("nope", request=httpx.Request("GET", "https://api.github.com"),
                                            response=httpx.Response(404))

            def close(self):
                pass

        runs = sync_service.run_full_sync(db, make_client=lambda token: Denied())

        assert runs[0].status == "error"
        assert "could not be read by any connected GitHub account" in runs[0].detail
        assert RECONNECT_DETAIL in runs[0].detail


class TestCollapseIsNarrow:
    """The squash rule keys on GitHub's own "(#12)" suffix rather than on the subject
    alone. A looser rule swallows repeated chores that really are separate commits."""

    def _c(self, sha, message):
        return {"sha": sha, "message": message}

    def test_two_commits_that_merely_share_a_subject_both_count(self):
        kept, _, duplicates = sync_service.collapse_commits([
            self._c("a", "update dev dependencies"),
            self._c("b", "update dev dependencies"),
        ])
        assert [c["sha"] for c in kept] == ["a", "b"] and duplicates == 0

    def test_two_pull_requests_with_the_same_title_both_count(self):
        kept, _, duplicates = sync_service.collapse_commits([
            self._c("a", "fix the flaky test (#42)"),
            self._c("b", "fix the flaky test (#57)"),
        ])
        assert [c["sha"] for c in kept] == ["a", "b"] and duplicates == 0

    def test_a_squash_absorbing_several_identical_subjects_collapses_them_all(self):
        kept, _, duplicates = sync_service.collapse_commits([
            self._c("sq", "add parser (#42)"),
            self._c("b1", "add parser"),
            self._c("b2", "add parser"),
        ])
        assert [c["sha"] for c in kept] == ["sq"] and duplicates == 2

    def test_a_squash_of_differently_worded_commits_is_not_detected(self):
        """Recorded rather than fixed: nothing in the payload links a squash to branch
        commits whose subjects it did not reuse."""
        kept, _, duplicates = sync_service.collapse_commits([
            self._c("sq", "add the parser (#42)"),
            self._c("b1", "first go at parsing"),
            self._c("b2", "handle the empty case"),
        ])
        assert len(kept) == 3 and duplicates == 0

    def test_has_pr_number_reads_only_the_subject(self):
        assert sync_service.has_pr_number("add parser (#42)") is True
        assert sync_service.has_pr_number("add parser\n\ncloses (#42)") is False
        assert sync_service.has_pr_number("add parser") is False

class TestCommitDates:
    """A commit's stored date is the day it landed on the branch, not the day it was
    written. A rebase or a cherry-pick moves the author date behind the day the commit
    reached the branch, which would file it under a week it was not part of."""

    def _fake(self, authored, committed):
        commit = {"message": "did work"}
        if authored:
            commit["author"] = {"date": authored}
        if committed:
            commit["committer"] = {"date": committed}
        return FakeGitHub(commits=[{"sha": "abc", "html_url": "u", "author": {"login": "ada"}, "commit": commit}])

    def test_a_rebased_commit_is_stored_under_the_date_it_landed(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db)
        fake = self._fake("2026-07-14T10:00:00Z", "2026-08-11T10:00:00Z")

        sync_service.run_full_sync(db, make_client=lambda t: fake)

        commit = db.scalar(select(Commit))
        assert commit.committed_at.isoformat().startswith("2026-08-11")

    def test_the_author_date_is_the_fallback_when_no_committer_block_is_sent(self):
        assert sync_service.commit_stamp({"commit": {"author": {"date": "2026-07-14T10:00:00Z"}}}) == "2026-07-14T10:00:00Z"

    def test_a_payload_with_neither_date_reads_as_missing(self):
        assert sync_service.commit_stamp({"commit": {"committer": {}}}) is None
        assert sync_service.commit_stamp({}) is None

class TestPullRequestClosure:
    """merged_at cannot date a pull request that was closed without being merged, and
    that was every closed unmerged pull request Pulse held before this column existed."""

    def _fake(self, **over):
        pr = {"id": 1, "number": 7, "title": "a PR", "state": "open", "merged_at": None,
              "closed_at": None, "created_at": "2026-07-19T10:00:00Z",
              "updated_at": "2026-07-20T10:00:00Z", "user": {"login": "ada"}, "html_url": "u"}
        return FakeGitHub(prs=[pr | over])

    def _sync(self, db, monkeypatch, fake):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db)
        sync_service.run_full_sync(db, make_client=lambda t: fake)
        return db.scalar(select(PullRequest))

    def test_a_pull_request_closed_without_merging_keeps_its_closure_date(self, db, monkeypatch):
        pr = self._sync(db, monkeypatch, self._fake(state="closed", closed_at="2026-07-21T10:00:00Z"))
        assert pr.merged is False and pr.merged_at is None
        assert pr.closed_at.isoformat().startswith("2026-07-21")

    def test_a_merged_pull_request_carries_both_dates(self, db, monkeypatch):
        pr = self._sync(db, monkeypatch, self._fake(
            state="closed", merged_at="2026-07-21T10:00:00Z", closed_at="2026-07-21T10:00:00Z"))
        assert pr.merged is True
        assert pr.merged_at.isoformat().startswith("2026-07-21")
        assert pr.closed_at.isoformat().startswith("2026-07-21")

    def test_an_open_pull_request_has_no_closure_date(self, db, monkeypatch):
        pr = self._sync(db, monkeypatch, self._fake())
        assert pr.closed_at is None

class TestIssueAssignment:
    """Who an issue is queued to, which is what next week's goals are written from. The
    person who raised an issue is usually not the person who will do it."""

    def _fake(self, **over):
        issue = {"id": 22, "number": 3, "title": "a bug", "state": "open",
                 "created_at": "2026-07-18T09:00:00Z", "closed_at": None,
                 "user": {"login": "bob"}, "html_url": "u"}
        return FakeGitHub(issues=[issue | over])

    def _sync(self, db, monkeypatch, fake):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db)
        sync_service.run_full_sync(db, make_client=lambda t: fake)
        return db.scalar(select(Issue))

    def test_an_assignee_is_attributed_to_the_pulse_user(self, db, monkeypatch):
        issue = self._sync(db, monkeypatch, self._fake(assignee={"login": "ada"}))
        assert issue.author_github_login == "bob" and issue.author_user_id is None
        assert issue.assignee_github_login == "ada" and issue.assignee_user_id == 10

    def test_an_unassigned_issue_carries_nobody(self, db, monkeypatch):
        issue = self._sync(db, monkeypatch, self._fake(assignee=None))
        assert issue.assignee_github_login is None and issue.assignee_user_id is None

    def test_unassigning_clears_the_previous_assignee(self, db, monkeypatch):
        monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
        _connect_account(db)
        sync_service.run_full_sync(db, make_client=lambda t: self._fake(assignee={"login": "ada"}))
        sync_service.run_full_sync(db, make_client=lambda t: self._fake(assignee=None))
        issue = db.scalar(select(Issue))
        assert issue.assignee_github_login is None and issue.assignee_user_id is None

    def test_a_milestone_keeps_its_name_and_due_date(self, db, monkeypatch):
        issue = self._sync(db, monkeypatch, self._fake(
            milestone={"title": "Sprint 12", "due_on": "2026-08-03T07:00:00Z"}))
        assert issue.milestone_title == "Sprint 12"
        assert issue.milestone_due_on.isoformat().startswith("2026-08-03")

    def test_a_milestone_with_no_due_date_stores_the_name_alone(self, db, monkeypatch):
        issue = self._sync(db, monkeypatch, self._fake(milestone={"title": "Backlog", "due_on": None}))
        assert issue.milestone_title == "Backlog" and issue.milestone_due_on is None

"""Slice 4: the GitHub activity sync. The engine is driven by a fake GitHub
client (no network); a separate test exercises the real client's pagination +
rate-limit handling via httpx.MockTransport."""
import time

import httpx
from sqlalchemy import func, select

from app import crypto
from app.celery_app import celery
from app.config import settings
from app.models import Commit, GitHubAccount, Issue, PullRequest, Repository, Review, SyncRun
from app.services import sync as sync_service
from app.services.github_client import GitHubClient
import app.tasks  # noqa: F401 — registers the task on the celery app

REPO = {"id": 555, "name": "alpha", "full_name": "org/alpha", "private": False, "default_branch": "main", "owner": {"login": "org"}}


class FakeGitHub:
    """Duck-typed stand-in for GitHubClient. Records the `since` it was asked for."""

    def __init__(self, repo=REPO, commits=(), prs=(), reviews=None, issues=()):
        self._repo = repo
        self._commits = list(commits)
        self._prs = list(prs)
        self._reviews = reviews or {}
        self._issues = list(issues)
        self.commit_since = []

    def get_repo(self, full_name):
        return self._repo

    def list_commits(self, full_name, since=None):
        self.commit_since.append(since)
        return self._commits

    def list_pull_requests(self, full_name):
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
             "state": "open", "user": {"login": "ada"}},  # must be skipped
        ],
    )


def test_sync_pulls_and_attributes_activity(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    _connect_account(db)  # ada → user 10
    fake = _rich_fake()

    runs = sync_service.run_full_sync(db, make_client=lambda token: fake)

    assert len(runs) == 1 and runs[0].status == "success", runs[0].detail
    repo = db.scalar(select(Repository).where(Repository.github_repo_id == 555))
    assert repo is not None and repo.last_synced_at is not None
    assert runs[0].repo_id == repo.id

    commit = db.scalar(select(Commit))
    assert commit.sha == "abc" and commit.author_user_id == 10  # attributed to ada

    pr = db.scalar(select(PullRequest))
    assert pr.number == 7 and pr.author_user_id == 10

    review = db.scalar(select(Review))
    assert review.state == "approved" and review.reviewer_user_id is None  # bob isn't connected

    issues = db.scalars(select(Issue)).all()
    assert len(issues) == 1 and issues[0].number == 3  # the PR-as-issue was skipped


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
    # First pull has no cursor; the second asks GitHub only for changes "since".
    assert fake.commit_since[0] is None
    assert fake.commit_since[1] is not None


def test_no_repos_configured_records_a_no_op(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "")
    runs = sync_service.run_full_sync(db)
    assert len(runs) == 1 and runs[0].status == "success"
    assert "no repos" in runs[0].detail


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
    assert calls["n"] == 2       # it retried after the rate-limit response
    assert len(slept) == 1       # and waited exactly once


def test_client_follows_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"sha": "b"}])
        nxt = str(request.url.copy_merge_params({"page": "2"}))
        return httpx.Response(200, json=[{"sha": "a"}], headers={"Link": f'<{nxt}>; rel="next"'})

    client = GitHubClient("tok", base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    assert client.list_commits("org/alpha") == [{"sha": "a"}, {"sha": "b"}]


def test_daily_sync_is_registered_on_the_celery_app():
    assert "app.tasks.sync_all_repos" in celery.tasks
    assert "daily-github-sync" in celery.conf.beat_schedule
    assert celery.conf.beat_schedule["daily-github-sync"]["task"] == "app.tasks.sync_all_repos"

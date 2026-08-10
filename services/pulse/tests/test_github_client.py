import time
import httpx
import pytest
from app.config import settings
from app.models import GitHubAccount, SyncRun
from app import crypto
from app.services import sync as sync_service
from app.services.github_client import GitHubClient, GitHubRateLimited


def _client(handler, slept, max_wait_seconds=60):
    return GitHubClient("tok", base_url="https://api.github.test", sleep=slept.append,
                        max_wait_seconds=max_wait_seconds, transport=httpx.MockTransport(handler))


def test_short_waits_are_retried_more_than_once():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "1", "X-RateLimit-Remaining": "0"}, json=[])
        return httpx.Response(200, json=[{"sha": "x"}])

    slept: list = []
    out = _client(handler, slept).list_commits("org/alpha")

    assert out == [{"sha": "x"}]
    assert calls["n"] == 3
    assert len(slept) == 2
    assert all(s <= 60 for s in slept)
    assert slept[1] >= slept[0]


def test_a_long_wait_is_refused_immediately():
    reset = int(time.time()) + 45 * 60

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}, json=[])

    slept: list = []
    with pytest.raises(GitHubRateLimited) as exc:
        _client(handler, slept).list_commits("org/alpha")

    assert slept == []
    assert exc.value.wait_seconds > 60
    assert "45 min" in str(exc.value)
    assert exc.value.resume_at is not None


def test_short_waits_stop_after_a_bounded_number_of_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json=[])

    slept: list = []
    with pytest.raises(GitHubRateLimited):
        _client(handler, slept).list_commits("org/alpha")

    assert calls["n"] == 4
    assert len(slept) == 3
    assert sum(slept) <= 60


def test_sync_records_a_rate_limited_run_distinguishably(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    db.add(GitHubAccount(user_id=10, github_user_id=99, github_login="ada",
                         access_token_encrypted=crypto.encrypt("gho_token")))
    db.commit()

    class Limited:
        def get_repo(self, full_name):
            raise GitHubRateLimited(45 * 60, f"https://api.github.test/repos/{full_name}")

        def close(self):
            pass

    runs = sync_service.run_full_sync(db, make_client=lambda token: Limited())

    assert len(runs) == 1
    assert runs[0].status == "rate_limited"
    assert "rate limit" in runs[0].detail.lower()
    assert "45 min" in runs[0].detail
    assert db.query(SyncRun).filter(SyncRun.status == "error").count() == 0

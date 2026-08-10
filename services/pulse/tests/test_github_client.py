"""The real GitHub client's rate-limit handling, driven by httpx.MockTransport (no
network) and an injected sleep (no real waits).

GitHub's primary limit resets on the hour, so a real exhaustion can be ~an hour away.
Two cases have to behave differently: a SHORT wait is slept through and retried, a LONG
wait is refused immediately and surfaced as GitHubRateLimited so the sync records it as
rate-limited rather than burying it in a generic error.
"""
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
    # Two rate-limited responses in a row, both with a short reset: it should ride out
    # both instead of giving up after the first retry.
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
    assert all(s <= 60 for s in slept)     # never blocks longer than max_wait_seconds
    assert slept[1] >= slept[0]            # backs off rather than hammering


def test_a_long_wait_is_refused_immediately():
    # Primary quota gone, reset 45 minutes out. Waiting would pin a worker for 45
    # minutes, so it must raise instead — and without sleeping at all.
    reset = int(time.time()) + 45 * 60

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}, json=[])

    slept: list = []
    with pytest.raises(GitHubRateLimited) as exc:
        _client(handler, slept).list_commits("org/alpha")

    assert slept == []                       # nothing blocked
    assert exc.value.wait_seconds > 60
    assert "45 min" in str(exc.value)        # the message says when it can resume
    assert exc.value.resume_at is not None


def test_short_waits_stop_after_a_bounded_number_of_retries():
    # Rate limited forever with a short reset: retries are bounded, and the outcome is
    # still the typed rate-limit error, not a generic HTTP error.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json=[])

    slept: list = []
    with pytest.raises(GitHubRateLimited):
        _client(handler, slept).list_commits("org/alpha")

    assert calls["n"] == 4      # first try + 3 retries
    assert len(slept) == 3
    assert sum(slept) <= 60     # bounded blocking


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
    assert runs[0].status == "rate_limited"        # not "error"
    assert "rate limit" in runs[0].detail.lower()
    assert "45 min" in runs[0].detail              # roughly when it can resume
    assert db.query(SyncRun).filter(SyncRun.status == "error").count() == 0

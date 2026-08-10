import logging
import pytest
from crescent_core.identity_client import IdentityUnavailable
from crescent_core.revocation import RevocationChecker, Verdict

class FakeClient:
    """Stands in for ServiceTokenClient. `bodies` is what identity replies with;
    `error` makes every lookup fail. Counts calls so cache tests can assert on them."""

    def __init__(self, versions: dict[int, int] | None = None, unknown: list[int] | None = None, error: Exception | None = None, body=None):
        self.versions = versions or {}
        self.unknown = unknown or []
        self.error = error
        self.body = body
        self.calls: list[list[int]] = []

    def lookup(self, path, user_ids):
        self.calls.append(list(user_ids))
        if self.error is not None:
            raise self.error
        if self.body is not None:
            return self.body
        return {
            "users": [{"user_id": uid, "token_version": tv} for uid, tv in self.versions.items() if uid in user_ids],
            "unknown_user_ids": [uid for uid in self.unknown if uid in user_ids],
        }

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

@pytest.fixture
def clock():
    return Clock()

def test_matching_token_version_is_current(clock):
    checker = RevocationChecker(FakeClient({7: 3}), clock=clock)
    assert checker.check(7, 3) is Verdict.CURRENT

def test_lower_token_version_is_stale(clock):
    checker = RevocationChecker(FakeClient({7: 4}), clock=clock)
    assert checker.check(7, 3) is Verdict.STALE

def test_higher_token_version_is_not_treated_as_stale(clock):
    """A token ahead of identity can only be a lagging read; rejecting would log out
    users identity never revoked."""
    checker = RevocationChecker(FakeClient({7: 1}), clock=clock)
    assert checker.check(7, 5) is Verdict.CURRENT

def test_unknown_user_id_is_unknown(clock):
    checker = RevocationChecker(FakeClient(unknown=[7]), clock=clock)
    assert checker.check(7, 0) is Verdict.UNKNOWN

def test_lookup_failure_is_unavailable_not_unknown(clock):
    """The dangerous mistake: reading a failed lookup as "no such user" would log
    every user out the moment identity blinked."""
    checker = RevocationChecker(FakeClient(error=IdentityUnavailable("identity down")), clock=clock)
    assert checker.check(7, 0) is Verdict.UNAVAILABLE
    assert checker.check(7, 0) is not Verdict.UNKNOWN

def test_unexpected_exception_is_unavailable_not_unknown(clock):
    checker = RevocationChecker(FakeClient(error=RuntimeError("boom")), clock=clock)
    assert checker.check(7, 0) is Verdict.UNAVAILABLE

def test_silence_about_an_id_is_unavailable_not_unknown(clock):
    """Identity answered but never mentioned this id — that is silence, not a verdict."""
    checker = RevocationChecker(FakeClient(body={"users": [], "unknown_user_ids": []}), clock=clock)
    assert checker.check(7, 0) is Verdict.UNAVAILABLE

def test_malformed_row_is_unavailable_not_unknown(clock):
    checker = RevocationChecker(FakeClient(body={"users": [{"user_id": 7}]}), clock=clock)
    assert checker.check(7, 0) is Verdict.UNAVAILABLE

def test_answer_is_keyed_by_user_id_not_position(clock):
    """Identity orders by id, not by the request, so position means nothing."""
    client = FakeClient()
    client.body = {
        "users": [{"user_id": 2, "token_version": 9}, {"user_id": 7, "token_version": 0}],
        "unknown_user_ids": [],
    }
    checker = RevocationChecker(client, clock=clock)
    assert checker.check(7, 0) is Verdict.CURRENT

def test_repeat_checks_inside_the_ttl_do_not_call_identity(clock):
    client = FakeClient({7: 0})
    checker = RevocationChecker(client, ttl_seconds=60.0, clock=clock)
    for _ in range(20):
        assert checker.check(7, 0) is Verdict.CURRENT
    assert len(client.calls) == 1

def test_cache_expires_after_the_ttl(clock):
    client = FakeClient({7: 0})
    checker = RevocationChecker(client, ttl_seconds=60.0, clock=clock)
    assert checker.check(7, 0) is Verdict.CURRENT
    clock.now += 61
    client.versions[7] = 1
    assert checker.check(7, 0) is Verdict.STALE
    assert len(client.calls) == 2

def test_each_user_is_cached_separately(clock):
    client = FakeClient({7: 0, 8: 0})
    checker = RevocationChecker(client, clock=clock)
    checker.check(7, 0)
    checker.check(8, 0)
    checker.check(7, 0)
    assert client.calls == [[7], [8]]

def test_failed_lookups_back_off_instead_of_calling_per_request(clock):
    client = FakeClient(error=IdentityUnavailable("identity down"))
    checker = RevocationChecker(client, failure_backoff_seconds=10.0, clock=clock)
    for _ in range(10):
        assert checker.check(7, 0) is Verdict.UNAVAILABLE
    assert len(client.calls) == 1
    clock.now += 11
    assert checker.check(7, 0) is Verdict.UNAVAILABLE
    assert len(client.calls) == 2

def test_outage_recovers_without_a_restart(clock):
    client = FakeClient(error=IdentityUnavailable("identity down"))
    checker = RevocationChecker(client, failure_backoff_seconds=10.0, clock=clock)
    assert checker.check(7, 0) is Verdict.UNAVAILABLE
    client.error = None
    client.versions = {7: 2}
    clock.now += 11
    assert checker.check(7, 0) is Verdict.STALE

def test_unavailable_is_logged_not_silent(clock, caplog):
    checker = RevocationChecker(FakeClient(error=IdentityUnavailable("identity down")), clock=clock)
    with caplog.at_level(logging.WARNING, logger="crescent_core.revocation"):
        checker.check(7, 0)
    assert "unavailable" in caplog.text
    assert "identity down" in caplog.text

def test_unavailable_logging_is_throttled_but_reports_the_count(clock, caplog):
    client = FakeClient(error=IdentityUnavailable("identity down"))
    checker = RevocationChecker(client, failure_backoff_seconds=0.0, log_interval_seconds=30.0, clock=clock)
    with caplog.at_level(logging.WARNING, logger="crescent_core.revocation"):
        for _ in range(5):
            checker.check(7, 0)
        assert len(caplog.records) == 1
        clock.now += 31
        checker.check(7, 0)
    assert len(caplog.records) == 2
    assert "5 since last report" in caplog.records[1].getMessage()

def test_unknown_is_not_cached(clock):
    """An id can start existing; pinning "unknown" for the TTL would reject a user
    created seconds ago."""
    client = FakeClient(unknown=[7])
    checker = RevocationChecker(client, clock=clock)
    assert checker.check(7, 0) is Verdict.UNKNOWN
    client.unknown = []
    client.versions = {7: 0}
    assert checker.check(7, 0) is Verdict.CURRENT

def test_clear_forces_a_fresh_lookup(clock):
    client = FakeClient({7: 0})
    checker = RevocationChecker(client, clock=clock)
    checker.check(7, 0)
    checker.clear()
    checker.check(7, 0)
    assert len(client.calls) == 2

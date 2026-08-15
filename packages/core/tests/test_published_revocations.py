import logging
import pytest
from crescent_core.published_revocations import Published, PublishedRevocations, SESSION_KEY_PREFIX, USER_KEY_PREFIX, published_revocations_from_url

class _FakeRedis:
    """mget only, which is the whole surface this consumer uses. Writes are recorded as
    attribute access failures: the class has no set/delete, so a consumer that tried
    would raise instead of quietly mutating identity's keys."""

    def __init__(self, store: dict | None = None, error: Exception | None = None):
        self.store = store or {}
        self.error = error
        self.seen: list[list[str]] = []

    def mget(self, keys):
        self.seen.append(list(keys))
        if self.error:
            raise self.error
        return [self.store.get(k) for k in keys]

def _consumer(store=None, error=None):
    client = _FakeRedis(store, error)
    return PublishedRevocations(client), client

def test_revoked_session_key_rejects():
    consumer, _ = _consumer({f"{SESSION_KEY_PREFIX}abc": b"1"})
    assert consumer.check(42, 3, "abc") is Published.REVOKED

def test_absent_keys_do_not_reject():
    consumer, _ = _consumer({})
    assert consumer.check(42, 3, "abc") is Published.NOT_REVOKED

def test_another_sessions_key_does_not_reject_this_one():
    consumer, _ = _consumer({f"{SESSION_KEY_PREFIX}other": b"1"})
    assert consumer.check(42, 3, "abc") is Published.NOT_REVOKED

def test_token_version_below_published_is_rejected():
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}42": b"5"})
    assert consumer.check(42, 4) is Published.REVOKED

def test_token_version_equal_to_published_is_accepted():
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}42": b"5"})
    assert consumer.check(42, 5) is Published.NOT_REVOKED

def test_token_version_above_published_is_accepted():
    # A lagging published value must never log out a session identity never revoked.
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}42": b"5"})
    assert consumer.check(42, 6) is Published.NOT_REVOKED

def test_another_users_key_does_not_reject():
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}99": b"9"})
    assert consumer.check(42, 0) is Published.NOT_REVOKED

def test_redis_error_is_unavailable_not_revoked():
    consumer, _ = _consumer(error=ConnectionError("connection refused"))
    assert consumer.check(42, 0, "abc") is Published.UNAVAILABLE

def test_redis_timeout_is_unavailable():
    consumer, _ = _consumer(error=TimeoutError("timed out"))
    assert consumer.check(42, 0) is Published.UNAVAILABLE

def test_unreadable_published_value_is_ignored():
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}42": b"not-a-number"})
    assert consumer.check(42, 0) is Published.NOT_REVOKED

def test_missing_sid_still_checks_the_user_key():
    consumer, client = _consumer({f"{USER_KEY_PREFIX}42": b"5"})
    assert consumer.check(42, 1, None) is Published.REVOKED
    assert client.seen == [[f"{USER_KEY_PREFIX}42"]]

def test_both_keys_are_read_in_one_round_trip():
    consumer, client = _consumer({})
    consumer.check(42, 1, "abc")
    assert client.seen == [[f"{SESSION_KEY_PREFIX}abc", f"{USER_KEY_PREFIX}42"]]

def test_string_values_work_as_well_as_bytes():
    consumer, _ = _consumer({f"{USER_KEY_PREFIX}42": "5"})
    assert consumer.check(42, 1) is Published.REVOKED

def test_outage_is_logged_at_warning_and_suppressed(caplog):
    ticks = iter([0.0, 1.0, 2.0, 100.0])
    consumer = PublishedRevocations(_FakeRedis(error=ConnectionError("down")), log_interval_seconds=30.0, clock=lambda: next(ticks))
    with caplog.at_level(logging.WARNING, logger="crescent_core.published_revocations"):
        for _ in range(4):
            consumer.check(42, 0)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2, messages
    assert "falling back to the token-version lookup" in messages[0]
    # The three suppressed attempts are counted, not lost.
    assert "(3 since last report)" in messages[1]

def test_from_url_returns_none_without_a_url():
    assert published_revocations_from_url("") is None
    assert published_revocations_from_url(None) is None

def test_from_url_returns_none_for_an_unusable_url():
    assert published_revocations_from_url("not-a-redis-url://x") is None

def test_from_url_builds_a_consumer_without_connecting():
    pytest.importorskip("redis")
    consumer = published_revocations_from_url("redis://unreachable-host:6379/0")
    assert isinstance(consumer, PublishedRevocations)

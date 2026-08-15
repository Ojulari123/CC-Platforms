import threading
import time
import httpx
import pytest
from crescent_core import JWKSClient, JWKSUnavailable

def _counting(doc_or_callable):
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        return doc_or_callable() if callable(doc_or_callable) else doc_or_callable

    return fetcher, calls

def test_client_caches_and_serves_key(jwks_doc, rsa_keypair):
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert calls["n"] == 1  # one fetch, second call served from cache

def test_unknown_kid_never_fetches_twice_in_one_call(jwks_doc):
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    assert client.get_key("not-in-doc") is None
    assert calls["n"] == 1

def test_repeated_unknown_kids_are_throttled_not_amplified(jwks_doc):
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    for i in range(20):
        assert client.get_key(f"forged-kid-{i}") is None  # every kid distinct
    assert calls["n"] == 1  # 20 unauthenticated requests, one call to identity

def test_a_rotated_key_becomes_usable_after_the_interval(jwks_doc, rsa_keypair):
    rotated = {**rsa_keypair["jwk"], "kid": "rotated-kid"}
    published = jwks_doc
    fetcher, calls = _counting(lambda: published)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0)

    assert client.get_key(rsa_keypair["kid"]) is not None
    assert calls["n"] == 1

    published = {"keys": [rotated]}  # identity rotates its signing key
    assert client.get_key("rotated-kid") is None  # still inside the interval
    assert calls["n"] == 1

    client._last_attempt_at -= 30.0  # interval elapses, worst case for a new key
    assert client.get_key("rotated-kid")["kid"] == "rotated-kid"
    assert calls["n"] == 2

def test_a_failed_fetch_leaves_cached_keys_working(jwks_doc, rsa_keypair):
    boom = False

    def fetcher():
        if boom:
            raise RuntimeError("identity unreachable")
        return jwks_doc

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=0.0)
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]

    boom = True
    client.invalidate()
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert client.get_key("not-in-doc") is None
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]

def test_an_empty_document_does_not_wipe_the_cache(jwks_doc, rsa_keypair):
    published = jwks_doc
    fetcher, calls = _counting(lambda: published)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=0.0)
    assert client.get_key(rsa_keypair["kid"]) is not None

    published = {"keys": []}
    client.invalidate()
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]

def test_an_unreachable_identity_raises_while_nothing_is_cached(rsa_keypair):
    def fetcher():
        raise RuntimeError("identity unreachable")

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0)
    with pytest.raises(JWKSUnavailable) as first:
        client.get_key(rsa_keypair["kid"])
    with pytest.raises(JWKSUnavailable):
        client.get_key(rsa_keypair["kid"])
    assert isinstance(first.value.__cause__, RuntimeError)  # the detail survives, for the log

def test_the_unavailable_error_carries_no_internal_detail(rsa_keypair):
    """It reaches a caller, so it must not name the url or repeat the transport error."""

    def fetcher():
        raise httpx.ConnectError("Connection refused to http://identity.internal:8001/jwks")

    client = JWKSClient(jwks_url="http://identity.internal:8001/jwks", fetcher=fetcher)
    with pytest.raises(JWKSUnavailable) as e:
        client.get_key(rsa_keypair["kid"])
    assert "identity.internal" not in str(e.value)
    assert "Connection refused" not in str(e.value)

def test_unavailable_is_still_caught_by_callers_watching_for_http_errors(rsa_keypair):
    """pulse and forge key their rate limiter off httpx.HTTPError to fall back to the
    caller's address when a token can't be verified. Narrowing the type must not turn
    that fallback into an unhandled error."""

    def fetcher():
        raise httpx.ConnectError("boom")

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    with pytest.raises(httpx.HTTPError):
        client.get_key(rsa_keypair["kid"])

def test_a_cold_cache_retries_the_next_request_instead_of_waiting_out_the_floor(jwks_doc, rsa_keypair):
    """The floor protects cached keys from forged kids. With nothing cached there is
    nothing to protect, and holding it meant one failed first fetch cost the process a
    full interval of certain failure."""
    up = False

    def fetcher():
        calls["n"] += 1
        if not up:
            raise RuntimeError("identity unreachable")
        return jwks_doc

    calls = {"n": 0}
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0, cold_retry_interval_seconds=0.0)

    with pytest.raises(JWKSUnavailable):
        client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 1

    with pytest.raises(JWKSUnavailable):
        client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 2  # a second attempt, well inside the 30s floor

    up = True
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert calls["n"] == 3  # recovers on the first request after identity returns

def test_cold_retries_are_still_bounded_per_process(rsa_keypair):
    """Immediate is not the same as unbounded: a dead identity must not take one
    outbound fetch per inbound request, or a recovering identity gets stampeded."""
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        raise RuntimeError("identity unreachable")

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0, cold_retry_interval_seconds=5.0)
    for _ in range(50):
        with pytest.raises(JWKSUnavailable):
            client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 1  # 50 requests, one fetch, because the cold floor still holds

def test_the_warm_floor_is_untouched_by_the_cold_one(jwks_doc, rsa_keypair):
    """Once keys are cached the long floor applies again, whatever the cold one is."""
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0, cold_retry_interval_seconds=0.0)
    assert client.get_key(rsa_keypair["kid"]) is not None
    assert calls["n"] == 1
    for i in range(50):
        assert client.get_key(f"forged-kid-{i}") is None
    assert calls["n"] == 1

def test_a_cold_retry_interval_never_exceeds_the_warm_one(rsa_keypair):
    client = JWKSClient(jwks_url="http://ignored", fetcher=lambda: {}, min_refresh_interval_seconds=2.0, cold_retry_interval_seconds=30.0)
    assert client._cold_retry_interval == 2.0

def _concurrent_get_key(client, kid, in_fetch, n=2):
    """First caller enters the fetch, then the rest pile in behind it."""
    results: dict[int, object] = {}

    def call(i):
        try:
            results[i] = client.get_key(kid)
        except Exception as e:
            results[i] = e

    threads = [threading.Thread(target=call, args=(0,))]
    threads[0].start()
    assert in_fetch.wait(5), "first caller never reached the fetch"
    for i in range(1, n):
        t = threading.Thread(target=call, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(10)
    return results

def test_a_second_caller_during_the_first_fetch_still_gets_the_key(jwks_doc, rsa_keypair):
    """The cold-start race: the refresh floor used to make everyone who arrived during
    the very first fetch return with an empty cache, which verify_access_token reports
    as "Unknown signing key" and the auth dependency turns into a 401. Order-dependent,
    so it looked intermittent; under --reload the window reopened on every edit."""
    in_fetch = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        in_fetch.set()
        release.wait(5)
        return jwks_doc

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0)
    results_holder = {}

    def run():
        results_holder.update(_concurrent_get_key(client, rsa_keypair["kid"], in_fetch, n=5))

    runner = threading.Thread(target=run)
    runner.start()
    assert in_fetch.wait(5)
    release.set()
    runner.join(15)

    assert calls["n"] == 1, "the refresh floor must still collapse this to one fetch"
    assert len(results_holder) == 5
    for i, key in results_holder.items():
        assert isinstance(key, dict) and key["kid"] == rsa_keypair["kid"], f"caller {i} got {key!r}"

def test_a_waiter_sees_the_same_failure_as_the_caller_that_fetched(rsa_keypair):
    """When the one real fetch fails, waiters must land on the same fail-closed path,
    not on a silent None that reads as a bad token."""
    in_fetch = threading.Event()
    release = threading.Event()

    def fetcher():
        in_fetch.set()
        release.wait(5)
        raise RuntimeError("identity unreachable")

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0)
    results_holder = {}

    def run():
        results_holder.update(_concurrent_get_key(client, rsa_keypair["kid"], in_fetch, n=3))

    runner = threading.Thread(target=run)
    runner.start()
    assert in_fetch.wait(5)
    release.set()
    runner.join(15)

    assert len(results_holder) == 3
    assert all(isinstance(r, JWKSUnavailable) for r in results_holder.values()), results_holder
    assert all(isinstance(r.__cause__, RuntimeError) for r in results_holder.values())

def test_a_failing_fetch_releases_its_waiters_without_a_second_fetch(rsa_keypair):
    """Waiters must not hang on a fetch that ends in an exception, and must not all
    turn round and re-fetch the moment they wake up either. The cold floor is what
    stops the second half of that: at 0.0 every woken waiter does fetch again."""
    in_fetch = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        in_fetch.set()
        release.wait(5)
        raise RuntimeError("identity unreachable")

    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher, min_refresh_interval_seconds=30.0)
    results_holder = {}

    def run():
        results_holder.update(_concurrent_get_key(client, rsa_keypair["kid"], in_fetch, n=6))

    runner = threading.Thread(target=run)
    runner.start()
    assert in_fetch.wait(5)
    release.set()
    started = time.monotonic()
    runner.join(15)
    assert not runner.is_alive(), "a waiter hung on a failed fetch"
    assert time.monotonic() - started < client._wait_timeout, "waiters sat out the full timeout"
    assert len(results_holder) == 6
    assert all(isinstance(r, JWKSUnavailable) for r in results_holder.values()), results_holder
    assert calls["n"] == 1, "the waiters stampeded a failing identity"

def test_invalidate_forces_refetch(jwks_doc, rsa_keypair):
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 1
    client.invalidate()  # must beat the interval floor, since it's a local, trusted signal
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 2

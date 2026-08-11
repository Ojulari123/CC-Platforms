import pytest
from crescent_core import JWKSClient

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
    with pytest.raises(RuntimeError):
        client.get_key(rsa_keypair["kid"])
    with pytest.raises(RuntimeError):
        client.get_key(rsa_keypair["kid"])

def test_invalidate_forces_refetch(jwks_doc, rsa_keypair):
    fetcher, calls = _counting(jwks_doc)
    client = JWKSClient(jwks_url="http://ignored", fetcher=fetcher)
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 1
    client.invalidate()  # must beat the interval floor, since it's a local, trusted signal
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 2

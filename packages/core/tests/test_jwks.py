from crescent_core import JWKSClient

def test_client_caches_and_serves_key(jwks_doc, rsa_keypair):
    calls = {"n": 0}

    def counting_fetcher():
        calls["n"] += 1
        return jwks_doc

    client = JWKSClient(jwks_url="http://ignored", fetcher=counting_fetcher)
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert client.get_key(rsa_keypair["kid"])["kid"] == rsa_keypair["kid"]
    assert calls["n"] == 1  # one fetch, second call served from cache

def test_unknown_kid_triggers_a_second_fetch(jwks_doc):
    calls = {"n": 0}

    def counting_fetcher():
        calls["n"] += 1
        return jwks_doc

    client = JWKSClient(jwks_url="http://ignored", fetcher=counting_fetcher)
    assert client.get_key("not-in-doc") is None
    # First call refreshes (TTL). Unknown kid triggers a second refresh in case
    # the doc updated. Two fetches expected.
    assert calls["n"] == 2

def test_invalidate_forces_refetch(jwks_doc, rsa_keypair):
    calls = {"n": 0}

    def counting_fetcher():
        calls["n"] += 1
        return jwks_doc

    client = JWKSClient(jwks_url="http://ignored", fetcher=counting_fetcher)
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 1
    client.invalidate()
    client.get_key(rsa_keypair["kid"])
    assert calls["n"] == 2

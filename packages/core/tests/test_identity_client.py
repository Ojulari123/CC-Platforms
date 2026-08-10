import httpx
import pytest
from crescent_core.identity_client import MAX_LOOKUP_IDS, IdentityUnavailable, ServiceTokenClient

class Poster:
    """Replays queued httpx.Response objects and records what was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.sent: list[tuple[str, dict, dict | None]] = []
        self.raises: Exception | None = None

    def __call__(self, url, json, headers=None):
        self.sent.append((url, json, headers))
        if self.raises is not None:
            raise self.raises
        return self.responses.pop(0)

def _token_response(expires_in=300, token="svc-token"):
    return httpx.Response(200, json={"access_token": token, "expires_in": expires_in})

def _client(poster, secret="shh"):
    return ServiceTokenClient(base_url="http://identity:8000/", client_id="forge", client_secret=secret, poster=poster)

def test_lookup_mints_a_token_then_calls_the_endpoint():
    poster = Poster(_token_response(), httpx.Response(200, json={"users": [], "unknown_user_ids": []}))
    body = _client(poster).lookup("/internal/users/token-versions", [1, 2])
    assert body == {"users": [], "unknown_user_ids": []}
    assert poster.sent[0][0] == "http://identity:8000/oauth/token"
    assert poster.sent[1][0] == "http://identity:8000/internal/users/token-versions"
    assert poster.sent[1][1] == {"user_ids": [1, 2]}
    assert poster.sent[1][2]["Authorization"] == "Bearer svc-token"

def test_service_token_is_reused_across_lookups():
    poster = Poster(_token_response(), httpx.Response(200, json={}), httpx.Response(200, json={}))
    client = _client(poster)
    client.lookup("/internal/users/token-versions", [1])
    client.lookup("/internal/users/token-versions", [2])
    assert sum(1 for url, *_ in poster.sent if url.endswith("/oauth/token")) == 1

def test_a_401_re_mints_the_token_once_and_retries():
    poster = Poster(
        _token_response(token="old"),
        httpx.Response(401),
        _token_response(token="new"),
        httpx.Response(200, json={"users": []}),
    )
    assert _client(poster).lookup("/internal/users/token-versions", [1]) == {"users": []}
    assert poster.sent[-1][2]["Authorization"] == "Bearer new"

def test_a_second_401_is_a_real_auth_failure():
    poster = Poster(_token_response(), httpx.Response(401), _token_response(), httpx.Response(401))
    with pytest.raises(IdentityUnavailable):
        _client(poster).lookup("/internal/users/token-versions", [1])

def test_network_error_raises_identity_unavailable():
    poster = Poster()
    poster.raises = httpx.ConnectError("no route to identity")
    with pytest.raises(IdentityUnavailable):
        _client(poster).lookup("/internal/users/token-versions", [1])

def test_error_status_raises_identity_unavailable():
    poster = Poster(_token_response(), httpx.Response(403))
    with pytest.raises(IdentityUnavailable) as e:
        _client(poster).lookup("/internal/users/token-versions", [1])
    assert "403" in str(e.value)

def test_rejected_credentials_raise_identity_unavailable():
    poster = Poster(httpx.Response(401))
    with pytest.raises(IdentityUnavailable):
        _client(poster).lookup("/internal/users/token-versions", [1])

def test_token_response_without_a_token_raises():
    poster = Poster(httpx.Response(200, json={"expires_in": 300}))
    with pytest.raises(IdentityUnavailable):
        _client(poster).lookup("/internal/users/token-versions", [1])

def test_unreadable_body_raises_identity_unavailable():
    poster = Poster(_token_response(), httpx.Response(200, content=b"not json"))
    with pytest.raises(IdentityUnavailable):
        _client(poster).lookup("/internal/users/token-versions", [1])

def test_missing_secret_refuses_to_call_identity():
    poster = Poster()
    client = _client(poster, secret="")
    assert client.configured is False
    with pytest.raises(IdentityUnavailable):
        client.lookup("/internal/users/token-versions", [1])
    assert poster.sent == []

def test_oversized_batch_is_a_programming_error_not_a_422():
    poster = Poster()
    with pytest.raises(ValueError):
        _client(poster).lookup("/internal/users/token-versions", list(range(MAX_LOOKUP_IDS + 1)))

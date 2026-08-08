"""The Pulse->identity service client: mint a client-credentials token, resolve
user_ids to emails, cache the token, and refetch-once on a 401.

No network: httpx.post is monkeypatched to a handler that dispatches on URL and
returns real httpx.Response objects (so .json()/.status_code behave for real).
"""
import httpx
import pytest
from app.config import settings
from app.services import identity_client
from app.services.identity_client import IdentityResolutionError, resolve_emails

TOKEN_URL = "http://identity:8000/oauth/token"
EMAILS_URL = "http://identity:8000/internal/users/emails"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    # A configured secret + a clean token cache before every test, since the cache
    # is module-level and would otherwise leak between tests.
    monkeypatch.setattr(settings, "IDENTITY_API_URL", "http://identity:8000")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_ID", "pulse")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "shh")
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    yield
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0


def _install(monkeypatch, handler):
    """Route identity_client's httpx.post through a URL-dispatching handler."""
    def _post(url, **kwargs):
        return handler(url, kwargs)
    monkeypatch.setattr(identity_client.httpx, "post", _post)


def test_token_fetch_then_email_lookup_happy_path(monkeypatch):
    calls = {"token": 0, "emails": 0}
    email_payloads = []

    def handler(url, kwargs):
        if url == TOKEN_URL:
            calls["token"] += 1
            assert kwargs["json"]["grant_type"] == "client_credentials"
            assert kwargs["json"]["client_secret"] == "shh"
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        assert url == EMAILS_URL
        calls["emails"] += 1
        assert kwargs["headers"]["Authorization"] == "Bearer svc-tok"
        email_payloads.append(kwargs["json"])
        return httpx.Response(200, json={"users": [
            {"user_id": 20, "email": "lead@x.com"},
            {"user_id": 25, "email": "deputy@x.com"},
        ]})

    _install(monkeypatch, handler)
    out = resolve_emails([20, 25])
    assert out == {20: "lead@x.com", 25: "deputy@x.com"}
    assert calls == {"token": 1, "emails": 1}
    assert email_payloads[0] == {"user_ids": [20, 25]}

    # A second call reuses the cached token — no new /oauth/token round-trip.
    resolve_emails([20])
    assert calls["token"] == 1
    assert calls["emails"] == 2


def test_401_triggers_one_refetch_and_retry(monkeypatch):
    calls = {"token": 0, "emails": 0}

    def handler(url, kwargs):
        if url == TOKEN_URL:
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{calls['token']}", "expires_in": 600})
        calls["emails"] += 1
        # First lookup is with the stale cached token -> 401; after a forced refetch the
        # retry succeeds.
        if calls["emails"] == 1:
            return httpx.Response(401, json={"detail": "expired"})
        assert kwargs["headers"]["Authorization"] == "Bearer tok-2"
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})

    _install(monkeypatch, handler)
    out = resolve_emails([20])
    assert out == {20: "lead@x.com"}
    assert calls["token"] == 2   # initial mint + one forced refetch
    assert calls["emails"] == 2  # first 401, then the retry


def test_empty_ids_short_circuits_without_calling(monkeypatch):
    def handler(url, kwargs):
        raise AssertionError("should not call identity for an empty id list")
    _install(monkeypatch, handler)
    assert resolve_emails([]) == {}


def test_missing_secret_raises_without_calling(monkeypatch):
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
    def handler(url, kwargs):
        raise AssertionError("should not call identity when unconfigured")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_token_endpoint_rejection_raises(monkeypatch):
    def handler(url, kwargs):
        return httpx.Response(401, json={"detail": "bad client"})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_token_response_without_access_token_raises(monkeypatch):
    def handler(url, kwargs):
        return httpx.Response(200, json={"expires_in": 600})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_transport_error_on_token_raises(monkeypatch):
    def handler(url, kwargs):
        raise httpx.ConnectError("identity unreachable")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_transport_error_on_lookup_raises(monkeypatch):
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        raise httpx.ConnectError("identity unreachable mid-lookup")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_lookup_500_raises(monkeypatch):
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        return httpx.Response(500, json={"detail": "boom"})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_missing_expires_in_falls_back_and_still_works(monkeypatch):
    # No expires_in -> short fallback life; the call still succeeds this time.
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok"})
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})
    _install(monkeypatch, handler)
    assert resolve_emails([20]) == {20: "lead@x.com"}

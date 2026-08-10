import httpx
from fastapi.routing import APIRoute
from crescent_core.revocation import Verdict
from app import auth
from app.config import settings
from app.main import app

def _uses(dependant, fn) -> bool:
    return any(d.call is fn or _uses(d, fn) for d in dependant.dependencies)

def test_every_dataset_route_goes_through_current_user():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/datasets")]
    assert routes
    assert all(_uses(r.dependant, auth.current_user) for r in routes)

def test_current_user_was_built_with_a_revocation_checker():
    assert auth.revocation_checker is not None
    assert auth.current_user.__closure__ is not None
    closed_over = [c.cell_contents for c in auth.current_user.__closure__]
    assert auth.revocation_checker in closed_over

def test_checker_ttl_comes_from_settings():
    assert auth.revocation_checker._ttl == settings.TOKEN_VERSION_TTL_SECONDS

def test_checker_calls_identity_at_the_configured_url_with_forges_client_id(monkeypatch):
    sent = []

    def poster(url, json, headers=None):
        sent.append((url, json, headers))
        if url.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "svc", "expires_in": 300})
        return httpx.Response(200, json={"users": [{"user_id": 5, "token_version": 2}], "unknown_user_ids": []})

    monkeypatch.setattr(auth.identity_client, "_poster", poster)
    monkeypatch.setattr(auth.identity_client, "_client_secret", "test-secret")
    auth.revocation_checker.clear()
    try:
        assert auth.revocation_checker.check(5, 1) is Verdict.STALE
    finally:
        auth.revocation_checker.clear()

    assert sent[0][0] == f"{settings.IDENTITY_API_URL}/oauth/token"
    assert sent[0][1]["client_id"] == settings.FORGE_SERVICE_CLIENT_ID
    assert sent[1][0] == f"{settings.IDENTITY_API_URL}/internal/users/token-versions"
    assert sent[1][1] == {"user_ids": [5]}

def test_unconfigured_secret_does_not_reject_callers():
    auth.revocation_checker.clear()
    try:
        assert auth.revocation_checker.check(5, 0) is Verdict.UNAVAILABLE
    finally:
        auth.revocation_checker.clear()

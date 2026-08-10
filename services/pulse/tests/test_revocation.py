"""Pulse-side wiring for the revocation check. The behaviour itself is covered in
packages/core; what matters here is that Pulse actually enables it, on every
authenticated route, pointed at the identity in its own settings."""
import httpx
from fastapi.routing import APIRoute
from crescent_core.revocation import Verdict
from app import auth
from app.config import settings
from app.main import app

# The only routes a signed-out browser is meant to reach.
PUBLIC_PATHS = {"/", "/health", "/github/oauth/callback"}

def _uses(dependant, fn) -> bool:
    return any(d.call is fn or _uses(d, fn) for d in dependant.dependencies)

def test_every_non_public_route_goes_through_current_user():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path not in PUBLIC_PATHS]
    assert routes
    unchecked = [r.path for r in routes if not _uses(r.dependant, auth.current_user)]
    assert unchecked == []

def test_current_user_was_built_with_a_revocation_checker():
    assert auth.revocation_checker is not None
    assert auth.current_user.__closure__ is not None
    closed_over = [c.cell_contents for c in auth.current_user.__closure__]
    assert auth.revocation_checker in closed_over

def test_checker_ttl_comes_from_settings():
    assert auth.revocation_checker._ttl == settings.TOKEN_VERSION_TTL_SECONDS

def test_revocation_timeout_is_shorter_than_the_default():
    """This call is on the request path; a black-holed identity must not hold a caller
    for the full default timeout."""
    assert auth.identity_client._timeout == auth.REVOCATION_TIMEOUT_SECONDS < 10.0

def test_checker_calls_identity_at_the_configured_url_with_pulses_client_id(monkeypatch):
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
    assert sent[0][1]["client_id"] == settings.PULSE_SERVICE_CLIENT_ID
    assert sent[1][0] == f"{settings.IDENTITY_API_URL}/internal/users/token-versions"
    assert sent[1][1] == {"user_ids": [5]}

def test_repeat_checks_inside_the_ttl_hit_identity_once(monkeypatch):
    lookups = []

    def poster(url, json, headers=None):
        if url.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "svc", "expires_in": 300})
        lookups.append(json)
        return httpx.Response(200, json={"users": [{"user_id": 5, "token_version": 1}], "unknown_user_ids": []})

    monkeypatch.setattr(auth.identity_client, "_poster", poster)
    monkeypatch.setattr(auth.identity_client, "_client_secret", "test-secret")
    auth.revocation_checker.clear()
    try:
        for _ in range(5):
            assert auth.revocation_checker.check(5, 1) is Verdict.CURRENT
    finally:
        auth.revocation_checker.clear()

    assert len(lookups) == 1

def test_unconfigured_secret_does_not_reject_callers():
    """CI and any deploy without the secret must degrade to "unchecked", not "locked out"."""
    auth.revocation_checker.clear()
    try:
        assert auth.revocation_checker.check(5, 0) is Verdict.UNAVAILABLE
    finally:
        auth.revocation_checker.clear()

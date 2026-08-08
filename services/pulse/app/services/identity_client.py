"""Pulse talking to identity as a *service* (not as a user).

Pulse stores approvers by user_id only (Rule 3: products reference identity by id,
never keep their own copy of the user). To email an approver we have to resolve
user_id -> address, which only identity can do. This module does the two-step
service-to-service dance:

  1. authenticate as the "pulse" client via OAuth2 client-credentials -> a short-lived
     scoped service token (scope users:read:email), and
  2. POST that token to identity's internal email-lookup endpoint.

The token is cached in-process and reused until it's about to expire, so a burst of
submits doesn't mint a fresh token every time. Any failure raises IdentityResolutionError
— this module never swallows, so it stays testable; the notify layer decides to log-and-skip.
"""

import threading
import time
import httpx
from app.config import settings

HTTP_TIMEOUT = 10.0
# Refresh the cached token this many seconds BEFORE it actually expires, so we never
# hand out a token that dies mid-request against identity.
TOKEN_EXPIRY_SKEW_SECONDS = 30

class IdentityResolutionError(Exception):
    """Couldn't reach identity, authenticate, or resolve emails. Caller decides what to do."""

# Module-level token cache. A lock keeps two concurrent submits from racing to mint
# tokens; the worst case without it is a wasted extra call, but the lock is cheap.
_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_expiry: float = 0.0  # monotonic-clock deadline; 0 means "nothing cached"

def _fetch_service_token() -> str:
    """Mint a fresh service token via client-credentials and cache it with its expiry."""
    global _cached_token, _cached_expiry
    try:
        resp = httpx.post(
            f"{settings.IDENTITY_API_URL}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": settings.PULSE_SERVICE_CLIENT_ID,
                "client_secret": settings.PULSE_SERVICE_CLIENT_SECRET,
            },
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise IdentityResolutionError(f"Could not reach identity for a service token: {e}") from e
    if resp.status_code >= 400:
        raise IdentityResolutionError(f"Identity rejected the service credentials (HTTP {resp.status_code})")
    body = resp.json()
    token = body.get("access_token")
    expires_in = body.get("expires_in")
    if not token:
        raise IdentityResolutionError("Identity returned no access_token")
    _cached_token = token
    # Fall back to a short life if identity omits expires_in, so a bad response can't
    # pin a stale token forever.
    _cached_expiry = time.monotonic() + max(int(expires_in or 60) - TOKEN_EXPIRY_SKEW_SECONDS, 0)
    return token

def _get_service_token(force_refresh: bool = False) -> str:
    """Return a usable service token, minting a new one only when the cache is empty,
    near expiry, or a caller forces it (after a 401)."""
    global _cached_token
    with _token_lock:
        if force_refresh or _cached_token is None or time.monotonic() >= _cached_expiry:
            return _fetch_service_token()
        return _cached_token

def _lookup_emails(token: str, user_ids: list[int]) -> httpx.Response:
    return httpx.post(
        f"{settings.IDENTITY_API_URL}/internal/users/emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_ids": user_ids},
        timeout=HTTP_TIMEOUT,
    )

def resolve_emails(user_ids: list[int]) -> dict[int, str]:
    """Resolve user_ids -> {user_id: email} via identity. Unknown ids are omitted by
    identity, so the returned dict may be smaller than the input.

    Raises IdentityResolutionError on any failure (unconfigured, identity down, auth
    rejected, bad response). An empty input short-circuits to {} without a call."""
    if not user_ids:
        return {}
    # No secret means this deploy hasn't been wired up to identity — refuse to call so
    # the caller can log-and-skip cleanly instead of firing doomed requests.
    if not settings.PULSE_SERVICE_CLIENT_SECRET:
        raise IdentityResolutionError("PULSE_SERVICE_CLIENT_SECRET is not set; cannot resolve emails")

    token = _get_service_token()
    try:
        resp = _lookup_emails(token, user_ids)
        # A cached token can go stale (rotated/revoked) between submits. On a 401, mint
        # a fresh one once and retry; a second 401 is a real auth problem, not staleness.
        if resp.status_code == 401:
            token = _get_service_token(force_refresh=True)
            resp = _lookup_emails(token, user_ids)
    except httpx.HTTPError as e:
        raise IdentityResolutionError(f"Could not reach identity to resolve emails: {e}") from e
    if resp.status_code >= 400:
        raise IdentityResolutionError(f"Identity email lookup failed (HTTP {resp.status_code})")

    users = resp.json().get("users", [])
    return {u["user_id"]: u["email"] for u in users}

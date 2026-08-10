"""Pulse talking to identity as a *service* (not as a user).

Pulse stores approvers by user_id only (Rule 3: products reference identity by id,
never keep their own copy of the user). To email an approver we have to resolve
user_id -> address, which only identity can do. This module does the two-step
service-to-service dance:

  1. authenticate as the "pulse" client via OAuth2 client-credentials -> a short-lived
     scoped service token (scope users:read:email), and
  2. POST that token to identity's internal lookup endpoints — emails (for notifications)
     and profiles (names/avatars, so responses can show a person instead of "user 6").

The token is cached in-process and reused until it's about to expire, so a burst of
submits doesn't mint a fresh token every time. Any failure raises IdentityResolutionError
— this module never swallows, so it stays testable; the notify layer decides to log-and-skip.
resolve_profiles_safe is the one exception: name resolution is decoration, so it swallows
on the caller's behalf. resolve_profiles_answer also swallows, but reports what identity
said rather than flattening it — see ProfileAnswer.
"""

import logging
import threading
import time
from typing import NamedTuple
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10.0
# Refresh the cached token this many seconds BEFORE it actually expires, so we never
# hand out a token that dies mid-request against identity.
TOKEN_EXPIRY_SKEW_SECONDS = 30
# Identity rejects an id batch larger than this with a 422, so we chunk.
MAX_LOOKUP_IDS = 200
# Names/avatars change on the order of days, and Pulse only uses them to draw a person
# (never to decide permissions — those come from the token), so stale data is cosmetic.
# Five minutes collapses a whole browsing session into one lookup per person while
# keeping a rename or deactivation visible without a restart.
PROFILE_CACHE_TTL_SECONDS = 300

class IdentityResolutionError(Exception):
    """Couldn't reach identity, authenticate, or resolve emails. Caller decides what to do."""

# Module-level token cache. A lock keeps two concurrent submits from racing to mint
# tokens; the worst case without it is a wasted extra call, but the lock is cheap.
_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_expiry: float = 0.0  # monotonic-clock deadline; 0 means "nothing cached"

def _fetch_service_token() -> str:
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
    global _cached_token
    with _token_lock:
        if force_refresh or _cached_token is None or time.monotonic() >= _cached_expiry:
            return _fetch_service_token()
        return _cached_token

def _post(path: str, token: str, user_ids: list[int]) -> httpx.Response:
    return httpx.post(
        f"{settings.IDENTITY_API_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_ids": user_ids},
        timeout=HTTP_TIMEOUT,
    )

def _lookup_body(path: str, what: str, user_ids: list[int]) -> dict:
    """One authenticated id-batch lookup against an internal identity endpoint.
    Returns the decoded body; raises IdentityResolutionError on anything that went
    wrong, so a caller can never mistake a failure for an answer."""
    token = _get_service_token()
    try:
        resp = _post(path, token, user_ids)
        # A cached token can go stale (rotated/revoked) between calls. On a 401, mint
        # a fresh one once and retry; a second 401 is a real auth problem, not staleness.
        if resp.status_code == 401:
            token = _get_service_token(force_refresh=True)
            resp = _post(path, token, user_ids)
    except httpx.HTTPError as e:
        raise IdentityResolutionError(f"Could not reach identity to resolve {what}: {e}") from e
    if resp.status_code >= 400:
        raise IdentityResolutionError(f"Identity {what} lookup failed (HTTP {resp.status_code})")
    return resp.json()

def _lookup(path: str, what: str, user_ids: list[int]) -> list[dict]:
    return _lookup_body(path, what, user_ids).get("users", [])

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
    return {u["user_id"]: u["email"] for u in _lookup("/internal/users/emails", "email", user_ids)}

# Profile cache: user_id -> (deadline, profile). Entries age independently so a batch
# resolved now doesn't reset the clock on one resolved four minutes ago.
_profile_lock = threading.Lock()
_profile_cache: dict[int, tuple[float, dict]] = {}

def _cached_profiles(user_ids: list[int]) -> tuple[dict[int, dict], list[int]]:
    """Split the wanted ids into what's still fresh in cache and what has to be fetched."""
    now = time.monotonic()
    hits: dict[int, dict] = {}
    misses: list[int] = []
    with _profile_lock:
        for uid in user_ids:
            entry = _profile_cache.get(uid)
            if entry and now < entry[0]:
                hits[uid] = entry[1]
            else:
                misses.append(uid)
    return hits, misses

def _store_profiles(profiles: dict[int, dict]) -> None:
    deadline = time.monotonic() + PROFILE_CACHE_TTL_SECONDS
    with _profile_lock:
        for uid, profile in profiles.items():
            _profile_cache[uid] = (deadline, profile)

def _profile_row(user: dict) -> dict:
    """Pin the fields Pulse depends on. A row identity sends without them raises here,
    inside resolve_profiles, where resolve_profiles_safe can turn it into 'no names'
    instead of a 500 further downstream."""
    return {
        "user_id": user["user_id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "avatar_url": user.get("avatar_url"),
        "is_active": user["is_active"],
    }

def clear_profile_cache() -> None:
    with _profile_lock:
        _profile_cache.clear()

class ProfileAnswer(NamedTuple):
    """Only what identity actually said. Both fields are statements identity made:
    `profiles` are ids it returned a row for, `unknown` are ids it explicitly listed
    in unknown_user_ids (it has no such user). An id in NEITHER means identity never
    answered about it — a chunk that timed out, 403'd or 500'd. Nothing here is
    derived by subtracting one from the request, so silence can never be read as
    "deleted", which is the difference between cleaning up after a leaver and wiping
    every stored credential during an identity outage."""
    profiles: dict[int, dict]
    unknown: set[int]

def _fetch_profiles(misses: list[int], tolerate_chunk_failure: bool) -> ProfileAnswer:
    """Fetch uncached ids in batches of MAX_LOOKUP_IDS. A chunk contributes to the
    result only once it has fully succeeded, so a failed chunk leaves its ids out of
    both fields rather than in `unknown`."""
    profiles: dict[int, dict] = {}
    unknown: set[int] = set()
    for start in range(0, len(misses), MAX_LOOKUP_IDS):
        chunk = misses[start:start + MAX_LOOKUP_IDS]
        try:
            body = _lookup_body("/internal/users/profiles", "profile", chunk)
            fetched = {u["user_id"]: _profile_row(u) for u in body.get("users", [])}
            chunk_unknown = set(body.get("unknown_user_ids") or [])
        except Exception as e:
            if not tolerate_chunk_failure:
                raise
            logger.warning("identity did not answer for %s of %s profile ids: %s", len(chunk), len(misses), e)
            continue
        # Cached per chunk, so if a later chunk fails the earlier ones aren't re-fetched.
        # Only successes are cached: an unknown id must not be pinned as unknown for the
        # TTL, since it may be a user created seconds ago or a scope that lands mid-rollout.
        _store_profiles(fetched)
        profiles.update(fetched)
        unknown.update(chunk_unknown)
    return ProfileAnswer(profiles, unknown)

def resolve_profiles(user_ids: list[int]) -> dict[int, dict]:
    """Resolve user_ids -> {user_id: profile} (first_name, last_name, avatar_url,
    is_active) via identity, serving what's cached and fetching the rest in batches of
    MAX_LOOKUP_IDS. Unknown ids are omitted by identity, so the returned dict may be
    smaller than the input. Keyed by the user_id identity sends back — the response
    order is the database's, not the request's.

    Raises IdentityResolutionError on any failure; use resolve_profiles_safe when a
    missing name must not break the response."""
    wanted = list(dict.fromkeys(uid for uid in user_ids if uid is not None))
    if not wanted:
        return {}
    resolved, misses = _cached_profiles(wanted)
    if not misses:
        return resolved
    if not settings.PULSE_SERVICE_CLIENT_SECRET:
        raise IdentityResolutionError("PULSE_SERVICE_CLIENT_SECRET is not set; cannot resolve profiles")

    resolved.update(_fetch_profiles(misses, tolerate_chunk_failure=False).profiles)
    return resolved

def resolve_profiles_safe(user_ids: list[int]) -> dict[int, dict]:
    """resolve_profiles that never raises. Identity being down, slow, or not yet
    granting users:read:profile (403 for a few minutes after a deploy, until identity
    restarts and old service tokens age out) means names are absent — it must never
    turn a working reports list into a 500."""
    try:
        return resolve_profiles(user_ids)
    except IdentityResolutionError as e:
        logger.warning("profile resolution skipped for %s ids: %s", len(user_ids), e)
        return {}
    except Exception as e:
        logger.error("profile resolution failed unexpectedly for %s ids: %s", len(user_ids), e)
        return {}

def resolve_profiles_answer(user_ids: list[int]) -> ProfileAnswer:
    """What identity says about these ids, with "no such user" kept apart from "no
    answer" — for callers that delete something on the strength of it. Never raises:
    a chunk identity couldn't answer is dropped from the result entirely, so a partial
    outage narrows the answer instead of widening `unknown`.

    resolve_profiles_safe stays the call for anything that only draws names; this one
    exists because a cleanup pass has to know the difference and a name doesn't."""
    wanted = list(dict.fromkeys(uid for uid in user_ids if uid is not None))
    if not wanted:
        return ProfileAnswer({}, set())
    cached, misses = _cached_profiles(wanted)
    if not misses:
        return ProfileAnswer(cached, set())
    if not settings.PULSE_SERVICE_CLIENT_SECRET:
        logger.warning("profile answer incomplete for %s ids: PULSE_SERVICE_CLIENT_SECRET is not set", len(wanted))
        return ProfileAnswer(cached, set())
    answer = _fetch_profiles(misses, tolerate_chunk_failure=True)
    return ProfileAnswer({**cached, **answer.profiles}, answer.unknown)

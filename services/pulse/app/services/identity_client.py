"""Pulse asks identity's internal endpoints over a service token; it never reads
identity's database, and stores nothing about a user beyond the id.

Anything that fails raises IdentityResolutionError rather than returning an empty
answer — a caller must never be able to mistake "identity didn't answer" for "identity
says there is no such user". resolve_profiles_safe swallows because names are
decoration; resolve_profiles_answer swallows but keeps the two apart (see ProfileAnswer).
"""

import logging
import threading
import time
from typing import NamedTuple
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10.0
TOKEN_EXPIRY_SKEW_SECONDS = 30
# Identity rejects an id batch larger than this with a 422, so we chunk.
MAX_LOOKUP_IDS = 200
PROFILE_CACHE_TTL_SECONDS = 300

class IdentityResolutionError(Exception):
    pass

_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_expiry: float = 0.0

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
    token = _get_service_token()
    try:
        resp = _post(path, token, user_ids)
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
    if not user_ids:
        return {}
    if not settings.PULSE_SERVICE_CLIENT_SECRET:
        raise IdentityResolutionError("PULSE_SERVICE_CLIENT_SECRET is not set; cannot resolve emails")
    return {u["user_id"]: u["email"] for u in _lookup("/internal/users/emails", "email", user_ids)}

_profile_lock = threading.Lock()
_profile_cache: dict[int, tuple[float, dict]] = {}

def _cached_profiles(user_ids: list[int]) -> tuple[dict[int, dict], list[int]]:
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
    """Only what identity actually said: `profiles` are ids it returned a row for,
    `unknown` are ids it explicitly listed in unknown_user_ids. An id in NEITHER means
    identity never answered about it. Nothing here is derived by subtracting one from
    the request, so silence can never be read as "deleted" — the difference between
    cleaning up after a leaver and wiping every stored credential during an outage."""
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
        # Only successes are cached: an unknown id must not be pinned as unknown for the
        # TTL, since it may be a user created seconds ago or a scope that lands mid-rollout.
        _store_profiles(fetched)
        profiles.update(fetched)
        unknown.update(chunk_unknown)
    return ProfileAnswer(profiles, unknown)

def resolve_profiles(user_ids: list[int]) -> dict[int, dict]:
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
    try:
        return resolve_profiles(user_ids)
    except IdentityResolutionError as e:
        logger.warning("profile resolution skipped for %s ids: %s", len(user_ids), e)
        return {}
    except Exception as e:
        logger.error("profile resolution failed unexpectedly for %s ids: %s", len(user_ids), e)
        return {}

def resolve_profiles_answer(user_ids: list[int]) -> ProfileAnswer:
    """For callers that delete something on the strength of the answer. Never raises: a
    chunk identity couldn't answer is dropped entirely, so a partial outage narrows the
    answer instead of widening `unknown`."""
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

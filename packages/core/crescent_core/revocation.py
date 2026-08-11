"""Tokens are verified locally against JWKS, so a revoked one keeps working for the rest of
its ~15 minutes. Asking identity for the user's current token_version, cached ~60s per user,
cuts a killed session's survival to about a minute."""
import logging
import threading
from enum import Enum
from typing import Callable
import time
from crescent_core.identity_client import IdentityUnavailable, ServiceTokenClient

logger = logging.getLogger(__name__)

TOKEN_VERSIONS_PATH = "/internal/users/token-versions"

class Verdict(str, Enum):
    """What identity actually said. UNAVAILABLE is the absence of an answer, and is
    deliberately not UNKNOWN, because reading a failed lookup as "deleted user" would log
    everyone out the moment identity blinked."""
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"

class RevocationChecker:

    def __init__(self, client: ServiceTokenClient, ttl_seconds: float = 60.0, failure_backoff_seconds: float = 10.0, log_interval_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._client = client
        self._ttl = ttl_seconds
        self._failure_backoff = failure_backoff_seconds
        self._log_interval = log_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[int, tuple[float, int | None]] = {}
        self._suppressed = 0
        self._next_log_at = 0.0

    def check(self, user_id: int, token_version: int) -> Verdict:
        cached = self._cached(user_id)
        if cached is not None:
            current = cached[1]
            return Verdict.UNAVAILABLE if current is None else self._compare(token_version, current)
        return self._fetch(user_id, token_version)

    def _cached(self, user_id: int) -> tuple[float, int | None] | None:
        now = self._clock()
        with self._lock:
            entry = self._cache.get(user_id)
            if entry and now < entry[0]:
                return entry
            return None

    def _store(self, user_id: int, current: int | None, ttl: float) -> None:
        with self._lock:
            self._cache[user_id] = (self._clock() + ttl, current)

    def _compare(self, token_version: int, current: int) -> Verdict:
        # A token_version ABOVE identity's is not treated as stale: that can only be a
        # lagging read, and rejecting on it would log out users identity never revoked.
        return Verdict.STALE if token_version < current else Verdict.CURRENT

    def _fetch(self, user_id: int, token_version: int) -> Verdict:
        try:
            body = self._client.lookup(TOKEN_VERSIONS_PATH, [user_id])
        except IdentityUnavailable as e:
            return self._unavailable(user_id, e)
        except Exception as e:
            return self._unavailable(user_id, e)

        try:
            # Keyed by the user_id identity sends back, never by position.
            versions = {int(u["user_id"]): int(u["token_version"]) for u in body.get("users") or []}
            unknown = {int(u) for u in body.get("unknown_user_ids") or []}
        except (KeyError, TypeError, ValueError) as e:
            return self._unavailable(user_id, e)

        current = versions.get(user_id)
        if current is not None:
            self._store(user_id, current, self._ttl)
            return self._compare(token_version, current)
        if user_id in unknown:
            # Identity said, in as many words, that it has no such user: deleted account.
            # Not cached: this rejects the request anyway, and an id can start existing.
            return Verdict.UNKNOWN
        # Identity answered without mentioning this id. That is silence, not "unknown".
        return self._unavailable(user_id, ValueError("identity answered without this user_id"))

    def _unavailable(self, user_id: int, err: Exception) -> Verdict:
        self._store(user_id, None, self._failure_backoff)
        self._log(err)
        return Verdict.UNAVAILABLE

    def _log(self, err: Exception) -> None:
        now = self._clock()
        with self._lock:
            self._suppressed += 1
            if now < self._next_log_at:
                return
            count, self._suppressed = self._suppressed, 0
            self._next_log_at = now + self._log_interval
        logger.warning("revocation check unavailable, tokens accepted unchecked (%s since last report): %s", count, err)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

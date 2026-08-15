"""Reads the revocations identity publishes to Redis, so a killed session dies on the
next request instead of surviving until the cached token_version expires.

The keys are identity's contract (services/identity/app/revocations.py), read-only here:

    revoked:sid:{sid}   = "1"      reject any token whose sid claim equals it
    revoked:user:{uid}  = "{tv}"   reject any token whose tv claim is BELOW this

Both expire after the access-token lifetime plus a skew margin, so absence is the normal
state and never means "revoked". Nothing in this module writes or deletes a key.

This is a fast path, not the authority, and it can only ever REJECT a token — never vouch
for one. Identity publishes best-effort: a write that failed leaves no key, so reading
"no key" as "this token is fine" would wave a genuinely revoked token through. So a
NOT_REVOKED answer still falls through to the token-version lookup in revocation.py,
which is the answer of record.

The failure direction is the same one deps.py already takes for the identity HTTP check:
a Redis outage returns UNAVAILABLE, which decides nothing and leaves the HTTP path in
charge. Losing Redis costs speed, not correctness — behaviour degrades to exactly what
existed before this module, never to a platform-wide rejection.
"""
import logging
import threading
import time
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = "revoked:sid:"
USER_KEY_PREFIX = "revoked:user:"

# This read sits on every authenticated request, so a wedged Redis has to cost
# milliseconds, not the seconds an identity HTTP call is allowed. Half a second is far
# under that and still wide enough not to flap on a GC pause or a container hiccup.
SOCKET_TIMEOUT_SECONDS = 0.5

class Published(str, Enum):
    """REVOKED is the only answer that decides anything. NOT_REVOKED means the keys read
    cleanly and none of them covers this token, which is not the same as "valid" — see
    the module docstring. UNAVAILABLE is the absence of an answer."""
    REVOKED = "revoked"
    NOT_REVOKED = "not_revoked"
    UNAVAILABLE = "unavailable"

class PublishedRevocations:

    def __init__(self, client, log_interval_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._client = client
        self._log_interval = log_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._suppressed = 0
        self._next_log_at = 0.0

    def check(self, user_id: int, token_version: int, session_id: str | None = None) -> Published:
        keys = []
        if session_id:
            keys.append(f"{SESSION_KEY_PREFIX}{session_id}")
        keys.append(f"{USER_KEY_PREFIX}{user_id}")
        try:
            # One round trip for both keys. Any redis-py failure — connection, timeout,
            # a client that was never usable — must degrade, never raise into a request,
            # so this catches broadly rather than importing RedisError and hoping the
            # list is complete.
            values = self._client.mget(keys)
        except Exception as e:
            self._log(e)
            return Published.UNAVAILABLE

        found = dict(zip(keys, values or []))
        if session_id and found.get(f"{SESSION_KEY_PREFIX}{session_id}") is not None:
            return Published.REVOKED

        published = self._as_int(found.get(f"{USER_KEY_PREFIX}{user_id}"))
        # A token_version at or ABOVE the published one is current: it was minted after
        # the revocation, or the key is simply the one that caused it. Only below is dead.
        if published is not None and token_version < published:
            return Published.REVOKED
        return Published.NOT_REVOKED

    def _as_int(self, value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            # A key we cannot read is not a verdict; leave it to the HTTP lookup.
            logger.warning("ignoring unreadable published token_version %r", value)
            return None

    def _log(self, err: Exception) -> None:
        now = self._clock()
        with self._lock:
            self._suppressed += 1
            if now < self._next_log_at:
                return
            count, self._suppressed = self._suppressed, 0
            self._next_log_at = now + self._log_interval
        logger.warning("published revocations unreadable, falling back to the token-version lookup (%s since last report): %s", count, err)

def published_revocations_from_url(url: str | None, socket_timeout_seconds: float = SOCKET_TIMEOUT_SECONDS) -> PublishedRevocations | None:
    """None when there is no Redis configured or redis-py isn't installed, which leaves
    the caller on exactly the pre-Redis path. from_url does not connect, so an
    unreachable Redis costs nothing until the first request."""
    if not url:
        return None
    try:
        from redis import Redis
    except ImportError:
        logger.warning("redis is not installed; revocations will only be seen through the token-version lookup")
        return None
    try:
        client = Redis.from_url(url, socket_connect_timeout=socket_timeout_seconds, socket_timeout=socket_timeout_seconds)
    except Exception as e:
        logger.warning("Redis URL unusable (%s); revocations will only be seen through the token-version lookup", e)
        return None
    return PublishedRevocations(client)

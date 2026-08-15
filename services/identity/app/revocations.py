"""Revocations published to Redis the moment they happen, so a product can learn about
one in a sub-millisecond lookup instead of waiting out its cached token_version.

The keys are a published contract, read-only for everyone else, in the same spirit as
/.well-known/jwks.json: identity publishes, products consume. Nothing here is
authoritative — identity's database is, and /internal/users/token-versions stays the
answer of record. A product that cannot reach Redis falls back to that and loses speed,
not correctness, which is why every write below is best-effort and never fails a request.

    revoked:sid:{session_id}  -> "1"                one session (one device) is finished
    revoked:user:{user_id}    -> "{token_version}"  every token below this version is dead

Both expire after the access-token lifetime plus a skew margin: once a token would have
expired on its own there is nothing left to revoke, so the key set stays tiny.
"""
import logging
from redis import Redis
from redis.exceptions import RedisError
from app.config import settings

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = "revoked:sid:"
USER_KEY_PREFIX = "revoked:user:"
# Covers clock drift between identity and whoever reads the key.
CLOCK_SKEW_SECONDS = 60
_SOCKET_TIMEOUT_SECONDS = 2

_client: Redis | None = None
_resolved = False

def _redis() -> Redis | None:
    """Lazy and cached. from_url does not connect, so an unreachable Redis costs nothing
    until the first revocation."""
    global _client, _resolved
    if _resolved:
        return _client
    _resolved = True
    if settings.REDIS_URL:
        try:
            _client = Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
                socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            )
        except (RedisError, ValueError) as exc:
            logger.warning("REDIS_URL %s unusable (%s); revocations will not be published", settings.REDIS_URL, exc)
    return _client

def reset_client() -> None:
    global _client, _resolved
    _client, _resolved = None, False

def ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + CLOCK_SKEW_SECONDS

def _publish(key: str, value: str) -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.set(key, value, ex=ttl_seconds())
    except RedisError as exc:
        # The database write already happened and is what makes the revocation real.
        # Swallowing this costs products their fast path until Redis is back, and they
        # still catch the revocation through the token-version lookup.
        logger.warning("could not publish %s to Redis (%s); products fall back to the token-version lookup", key, exc)

def publish_session_revoked(session_id: str) -> None:
    _publish(f"{SESSION_KEY_PREFIX}{session_id}", "1")

def publish_user_revoked(user_id: int, token_version: int) -> None:
    _publish(f"{USER_KEY_PREFIX}{user_id}", str(token_version))

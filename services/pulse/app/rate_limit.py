"""Counters live in Redis, not process memory: in-memory counters are per-process, so
two workers quietly double everyone's real limit and a restart wipes every tally."""
import logging
import httpx
from fastapi import Request
from limits.storage import storage_from_string
from slowapi import Limiter
from slowapi.util import get_remote_address
from crescent_core import InvalidToken, verify_access_token
from app.auth import jwks_client
from app.config import settings

logger = logging.getLogger(__name__)

# Short timeouts so a missing or wedged Redis can't hold up startup or a request.
_STORAGE_OPTIONS = {"socket_connect_timeout": 2, "socket_timeout": 2}

def _resolve_storage_uri() -> str | None:
    if not settings.REDIS_URL:
        return None
    try:
        reachable = storage_from_string(settings.REDIS_URL, **_STORAGE_OPTIONS).check()
    except Exception as exc:  # unparseable URL, missing driver, DNS blowing up
        logger.warning("Rate limit storage %s unusable (%s); falling back to in-memory counters", settings.REDIS_URL, exc)
        return None
    if not reachable:
        logger.warning("Rate limit storage %s unreachable; falling back to in-memory counters", settings.REDIS_URL)
        return None
    return settings.REDIS_URL

_storage_uri = _resolve_storage_uri()

_short_forwarded_header_warned = False

def client_address(request: Request) -> str:
    """X-Forwarded-For is caller-supplied, so trusting it unconditionally hands out a
    fresh bucket per made-up value — hence TRUST_PROXY_HEADERS. Each hop appends the
    address it saw, so the entry TRUSTED_PROXY_COUNT from the RIGHT is the last one a
    trusted proxy wrote; a header carrying fewer hops than that is not the one our
    proxies produce, so it is ignored entirely rather than read from its
    caller-supplied end.
    """
    global _short_forwarded_header_warned
    if settings.TRUST_PROXY_HEADERS:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= settings.TRUSTED_PROXY_COUNT:
            return hops[-settings.TRUSTED_PROXY_COUNT]
        if hops and not _short_forwarded_header_warned:
            _short_forwarded_header_warned = True
            logger.warning(
                "X-Forwarded-For had %d hop(s), fewer than TRUSTED_PROXY_COUNT=%d; using the "
                "socket address instead. Check the setting matches the proxies in front of this "
                "service. Further occurrences are not logged.",
                len(hops), settings.TRUSTED_PROXY_COUNT,
            )
    return get_remote_address(request)

def address_key(request: Request) -> str:
    return f"ip:{client_address(request)}"

def user_or_address_key(request: Request) -> str:
    """The token is verified in full rather than just decoded: a key taken from an
    unverified claim would let anyone forge a header for a fresh bucket, or aim one at
    someone else's — and on /reports/generate someone else's bucket is someone else's
    OpenAI spend. Anything unverifiable falls back to the address, never a shared key.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and token:
        try:
            claims = verify_access_token(token, jwks_client, settings.JWT_ISSUER)
            return f"user:{claims.user_id}"
        except (InvalidToken, httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
    return address_key(request)

# in_memory_fallback + swallow_errors: if Redis dies after boot, keep counting per-worker
# rather than letting everything through, and never 500 a request over a sick store.
limiter = Limiter(
    key_func=address_key,
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri=_storage_uri,
    storage_options=_STORAGE_OPTIONS if _storage_uri else {},
    swallow_errors=True,
    in_memory_fallback_enabled=True,
)

# slowapi attaches a handler that discards every record it emits, so a swallowed
# storage error — the one event that means limits are off — is invisible. Point its
# logger at uvicorn's error log so a degradation is actually visible.
limiter.logger.handlers.clear()
limiter.logger.setLevel(logging.WARNING)
for _handler in logging.getLogger("uvicorn.error").handlers:
    limiter.logger.addHandler(_handler)

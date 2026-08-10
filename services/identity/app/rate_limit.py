import logging
from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings
from app.security.jwt import decode_access_token

logger = logging.getLogger(__name__)

_short_forwarded_header_warned = False

def client_address(request: Request) -> str:
    # X-Forwarded-For is caller-supplied — only trust it behind proxies we run.
    # Count hops from the right; anything further left is caller-controlled.
    global _short_forwarded_header_warned
    if settings.TRUST_PROXY_HEADERS:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        # Fewer hops than proxies we claim to run means this is not the header we
        # expect, and its leftmost entry is wholly caller-supplied. The socket address
        # is the safer read.
        if len(hops) >= settings.TRUSTED_PROXY_COUNT:
            return hops[-settings.TRUSTED_PROXY_COUNT]
        if hops and not _short_forwarded_header_warned:
            # Once per process: a caller chooses this condition, so warning per request
            # would hand anyone a log-flooding lever.
            _short_forwarded_header_warned = True
            logger.warning(
                "X-Forwarded-For had %d hop(s), fewer than TRUSTED_PROXY_COUNT=%d; using the "
                "socket address instead. Check the setting matches the proxies in front of this "
                "service. Further occurrences are not logged.",
                len(hops), settings.TRUSTED_PROXY_COUNT,
            )
    return get_remote_address(request)

def address_key(request: Request) -> str:
    """Key for routes with no caller yet — login, signup, register, refresh, oauth/token."""
    return f"ip:{client_address(request)}"

def user_or_address_key(request: Request) -> str:
    # Verified in full, not just decoded: a key read from an unverified claim would
    # let anyone forge a fresh bucket or aim one at someone else's. Unusable tokens
    # fall back to the address, never a shared key. See README "Rate-limit keys".
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and token:
        try:
            return f"user:{decode_access_token(token).user_id}"
        except (HTTPException, KeyError, TypeError, ValueError):
            pass
    return address_key(request)

limiter = Limiter(key_func=address_key, enabled=settings.RATE_LIMIT_ENABLED)

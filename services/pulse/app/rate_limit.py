import logging
import httpx
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from crescent_core import InvalidToken, verify_access_token
from app.auth import jwks_client
from app.config import settings

logger = logging.getLogger(__name__)

_short_forwarded_header_warned = False

def client_address(request: Request) -> str:
    """The caller's address. Behind a proxy the direct peer is the proxy, so every
    caller would land in one bucket — but X-Forwarded-For is caller-supplied, and
    trusting it unconditionally hands out a fresh bucket per made-up value. Hence
    TRUST_PROXY_HEADERS, off unless the deployment really does sit behind proxies
    we run.

    Each hop appends the address it saw, so the entry TRUSTED_PROXY_COUNT from the
    RIGHT is the last one a trusted proxy wrote. Everything to its left came from
    the caller and can say anything. A header carrying fewer hops than that is not
    the one our proxies produce, so it is ignored entirely rather than read from its
    caller-supplied end.
    """
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
    """Key for routes with no caller to attribute the request to — the GitHub OAuth
    callback, which arrives as a plain browser redirect carrying a signed state."""
    return f"ip:{client_address(request)}"

def user_or_address_key(request: Request) -> str:
    """Key for authenticated routes. One person burning their quota must not lock
    out everyone else behind the same address (office NAT, a proxy, a mobile
    carrier).

    The key function runs before route dependencies, so identity has to come out
    of the Authorization header here. The token is verified in full against
    identity's published keys rather than just decoded: a key taken from an
    unverified claim would let anyone forge a header for a fresh bucket, or aim one
    at someone else's — and on /reports/generate someone else's bucket is someone
    else's OpenAI spend. The extra work is a public-key signature check against the
    cached JWKS, not a call to identity.

    Anything absent, malformed or unverifiable falls back to the address, never a
    shared or empty key. A JWKS fetch failing counts as unverifiable here — the
    request still fails in the auth dependency, but deriving the key must not be
    what breaks it.
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

limiter = Limiter(key_func=address_key, enabled=settings.RATE_LIMIT_ENABLED)

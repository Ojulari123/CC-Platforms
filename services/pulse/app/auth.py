"""How Pulse knows who's calling.

Tokens are minted by identity and verified here *locally* against identity's
published public keys — Pulse never calls identity to check a token, and never
touches identity's database. All of the verification logic lives in the shared 
`crescent_core` package so Pulse and Forge stay in step.

The one call Pulse does make is the revocation check: a locally-valid token says nothing
about whether the session was killed a minute ago, so identity's current token_version is
fetched (cached per user for TOKEN_VERSION_TTL_SECONDS) and a stale `tv` is rejected.
"""
from crescent_core import JWKSClient, RevocationChecker, ServiceTokenClient, current_user_dep
from app.config import settings

jwks_client = JWKSClient(settings.IDENTITY_JWKS_URL, ttl_seconds=settings.JWKS_TTL_SECONDS)

# Short on purpose: this call sits on the request path, so a black-holed identity must
# cost one caller a few seconds, not the full default timeout.
REVOCATION_TIMEOUT_SECONDS = 3.0

# Separate from app/services/identity_client.py on purpose: that one serves the slower
# off-path email/profile lookups and keeps the default timeout.
identity_client = ServiceTokenClient(
    base_url=settings.IDENTITY_API_URL,
    client_id=settings.PULSE_SERVICE_CLIENT_ID,
    client_secret=settings.PULSE_SERVICE_CLIENT_SECRET,
    timeout_seconds=REVOCATION_TIMEOUT_SECONDS,
)
revocation_checker = RevocationChecker(identity_client, ttl_seconds=settings.TOKEN_VERSION_TTL_SECONDS)

# Every authenticated route depends on this one object, so the check is never opt-in.
current_user = current_user_dep(jwks_client, issuer=settings.JWT_ISSUER, revocation_checker=revocation_checker)

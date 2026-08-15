"""Tokens are verified locally against identity's published public keys, so Pulse never
reads identity's database. The one call out is the revocation check: a locally-valid
token says nothing about whether the session was killed a minute ago.
"""
from crescent_core import JWKSClient, RevocationChecker, ServiceTokenClient, current_user_dep, published_revocations_from_url
from app.config import settings

jwks_client = JWKSClient(settings.IDENTITY_JWKS_URL, ttl_seconds=settings.JWKS_TTL_SECONDS)

REVOCATION_TIMEOUT_SECONDS = 3.0

identity_client = ServiceTokenClient(
    base_url=settings.IDENTITY_API_URL,
    client_id=settings.PULSE_SERVICE_CLIENT_ID,
    client_secret=settings.PULSE_SERVICE_CLIENT_SECRET,
    timeout_seconds=REVOCATION_TIMEOUT_SECONDS,
)
revocation_checker = RevocationChecker(identity_client, ttl_seconds=settings.TOKEN_VERSION_TTL_SECONDS)

# Identity's published revocations. None when REDIS_URL is blank, which leaves the
# checker above as the only path — and for a single killed session that path never says
# no, because revoke_session deliberately does not bump token_version.
published_revocations = published_revocations_from_url(settings.REDIS_URL)

current_user = current_user_dep(jwks_client, issuer=settings.JWT_ISSUER, revocation_checker=revocation_checker, published_revocations=published_revocations)

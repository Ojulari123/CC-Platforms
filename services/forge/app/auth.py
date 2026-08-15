from crescent_core import JWKSClient, RevocationChecker, ServiceTokenClient, current_user_dep, published_revocations_from_url
from app.config import settings

jwks_client = JWKSClient(settings.IDENTITY_JWKS_URL, ttl_seconds=settings.JWKS_TTL_SECONDS)

# Short on purpose: this call sits on the request path, so a black-holed identity must
# cost one caller a few seconds, not the full default timeout.
REVOCATION_TIMEOUT_SECONDS = 3.0

identity_client = ServiceTokenClient(
    base_url=settings.IDENTITY_API_URL,
    client_id=settings.FORGE_SERVICE_CLIENT_ID,
    client_secret=settings.FORGE_SERVICE_CLIENT_SECRET,
    timeout_seconds=REVOCATION_TIMEOUT_SECONDS,
)
revocation_checker = RevocationChecker(identity_client, ttl_seconds=settings.TOKEN_VERSION_TTL_SECONDS)

# Identity's published revocations. None when REDIS_URL is blank, which leaves the
# checker above as the only path — slower, but the same answers.
published_revocations = published_revocations_from_url(settings.REDIS_URL)

# Every authenticated route depends on this one object, so the check is never opt-in.
current_user = current_user_dep(jwks_client, issuer=settings.JWT_ISSUER, revocation_checker=revocation_checker, published_revocations=published_revocations)

from typing import Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from crescent_core.claims import TokenClaims
from crescent_core.jwks import JWKSClient, JWKSUnavailable
from crescent_core.published_revocations import Published, PublishedRevocations
from crescent_core.revocation import RevocationChecker, Verdict
from crescent_core.verify import InvalidToken, verify_access_token

_bearer = HTTPBearer(auto_error=False)

def current_user_dep(jwks_client: JWKSClient, issuer: str, revocation_checker: RevocationChecker | None = None, published_revocations: PublishedRevocations | None = None) -> Callable[..., TokenClaims]:
    def _current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> TokenClaims:
        if not creds or not creds.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            claims = verify_access_token(creds.credentials, jwks_client, issuer)
        except InvalidToken as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )
        except JWKSUnavailable:
            # Not 401: we never got far enough to judge the token, and a 401 would log
            # everyone out over an identity blip. Not 500 either: nothing here is
            # broken, a dependency is down. Fixed wording — the cause holds the url and
            # transport error and stays in the log. Retry-After matches the client's
            # cold-cache floor, which is how soon a retry can actually reach identity.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is temporarily unavailable",
                headers={"Retry-After": "1"},
            )
        if published_revocations is not None:
            # Redis first: it is the only path that catches a revocation within seconds
            # rather than within TOKEN_VERSION_TTL_SECONDS. Same fail-open rule as below
            # — only REVOKED decides anything, and NOT_REVOKED is deliberately not a pass,
            # because identity publishes best-effort and a missing key proves nothing.
            if published_revocations.check(claims.user_id, claims.token_version, claims.session_id) is Published.REVOKED:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session is no longer valid",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        if revocation_checker is not None:
            # Only an explicit answer from identity rejects. UNAVAILABLE is accepted on
            # purpose: failing closed would make an identity blip a platform-wide outage.
            verdict = revocation_checker.check(claims.user_id, claims.token_version)
            if verdict in (Verdict.STALE, Verdict.UNKNOWN):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session is no longer valid",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return claims

    return _current_user

def require_dept_role(current_user: Callable[..., TokenClaims], *allowed_roles: str) -> Callable[..., TokenClaims]:
    """`dept_id` is read from the URL path, so the check is always against the
    department actually being acted on, not one the caller happens to manage."""

    def _check(dept_id: int, user: TokenClaims = Depends(current_user)) -> TokenClaims:
        if user.is_platform_admin:
            return user
        role = user.role_in(dept_id)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this department",
            )
        if allowed_roles and role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return user

    return _check

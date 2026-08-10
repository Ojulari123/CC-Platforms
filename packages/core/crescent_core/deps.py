from typing import Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from crescent_core.claims import TokenClaims
from crescent_core.jwks import JWKSClient
from crescent_core.revocation import RevocationChecker, Verdict
from crescent_core.verify import InvalidToken, verify_access_token

_bearer = HTTPBearer(auto_error=False)

def current_user_dep(jwks_client: JWKSClient, issuer: str, revocation_checker: RevocationChecker | None = None) -> Callable[..., TokenClaims]:
    """Build the dependency once at startup and reuse the returned dep everywhere.
    Pass revocation_checker to also drop tokens identity has since revoked; without
    one the token's signature and expiry are the only gates (previous behaviour)."""

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
    department actually being acted on — a manager in Engineering does not get
    manager rights in Data."""

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

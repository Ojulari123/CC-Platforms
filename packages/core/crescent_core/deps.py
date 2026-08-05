from typing import Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from crescent_core.claims import TokenClaims
from crescent_core.jwks import JWKSClient
from crescent_core.verify import InvalidToken, verify_access_token

_bearer = HTTPBearer(auto_error=False)

def current_user_dep(jwks_client: JWKSClient, issuer: str) -> Callable[..., TokenClaims]:
    """Returns a FastAPI dependency that verifies the Authorization: Bearer
    token and yields TokenClaims. Products call this once at startup and reuse
    the returned dep everywhere."""

    def _current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> TokenClaims:
        if not creds or not creds.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return verify_access_token(creds.credentials, jwks_client, issuer)
        except InvalidToken as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _current_user

def require_dept_role(current_user: Callable[..., TokenClaims], *allowed_roles: str) -> Callable[..., TokenClaims]:
    """Gate an endpoint on the caller's role IN THE DEPARTMENT NAMED IN
    THE URL. `dept_id` is read from the path, so the check is always against the
    department actually being acted on.
    
    E.g. someone who is a manager in Engineering doesn't get manager rights in Data.

    Platform admins pass every check. Pass no roles to require membership only.
    """

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

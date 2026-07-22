from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from crescent_core.claims import TokenClaims
from crescent_core.jwks import JWKSClient
from crescent_core.verify import InvalidToken, verify_access_token

_bearer = HTTPBearer(auto_error=False)

def current_user_dep(jwks_client: JWKSClient, issuer: str):
    """Factory: returns a FastAPI dependency that verifies the Authorization: Bearer
    token and yields TokenClaims. Products call this once at startup."""

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

def require_role(*allowed_roles: str):
    """Factory: gate an endpoint on the caller's role claim. Use *after* current_user_dep.

    Example:
        manager_only = require_role("manager", "owner")
        @app.post("/reports/{id}/approve", dependencies=[Depends(current_user), Depends(manager_only)])"""

    def _check(user: TokenClaims) -> TokenClaims:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires one of roles: {', '.join(allowed_roles)}")
        return user

    return _check

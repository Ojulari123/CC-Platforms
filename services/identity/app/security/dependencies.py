from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, User
from app.security.jwt import decode_access_token

_bearer = HTTPBearer(auto_error=False)

def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    """Verify the access token and load the user. Checks:
    - signature + expiry + issuer + token_type (via decode_access_token)
    - user exists and is_active
    - payload.tv matches user.token_version (invalidates outstanding access tokens
      after password change or logout-everywhere)"""
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    payload = decode_access_token(creds.credentials)

    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    if payload.token_version != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked. Please log in again.", headers={"WWW-Authenticate": "Bearer"})
    return user

def get_current_membership(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Membership:
    """The caller's active department membership — carries dept_id and role.
    Callers never pass a dept_id: it comes from who they are, so there's no way
    to aim a request at a department you don't belong to."""
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not belong to a department yet")
    return membership

def require_role(*roles: str):
    """Factory: FastAPI dependency that requires the caller's department role to
    be one of `roles`. Yields the membership so routes get dept_id for free.

        admin_only = require_role("admin")

        @router.post("/teams")
        def create(m: Membership = Depends(admin_only)): ..."""

    def _check(membership: Membership = Depends(get_current_membership)) -> Membership:
        if membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires one of roles: {', '.join(roles)}")
        return membership

    return _check

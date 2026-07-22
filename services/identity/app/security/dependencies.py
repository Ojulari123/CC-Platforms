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

def require_org_role(db: Session, user: User, org_id: int, *roles: str) -> Membership:
    """Plain helper (not a FastAPI dep — org_id comes from the path). Returns the
    caller's active membership in the org, 403 if absent or role not allowed.
    Pass no roles to only require membership."""
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org_id, Membership.is_active.is_(True)))
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organisation")
    if roles and membership.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires one of roles: {', '.join(roles)}")
    return membership

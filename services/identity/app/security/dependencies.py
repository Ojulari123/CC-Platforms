from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, Team, User
from app.security.jwt import decode_access_token, decode_service_token

_bearer = HTTPBearer(auto_error=False)

def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    """Verify the token and load the user. The tv check is what makes outstanding
    access tokens die after a password change or logout-everywhere."""
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

def require_service_scope(scope: str):
    """Guard a service-to-service endpoint: a SERVICE token carrying `scope`. A user
    access token is rejected on token_type. Returns the payload, so the handler can
    see which client called."""

    def _check(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
        if not creds or not creds.credentials:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        payload = decode_service_token(creds.credentials)
        granted = payload.get("scope", "").split()
        if scope not in granted:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires scope: {scope}")
        return payload

    return _check

def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires a platform administrator")
    return user

def get_membership(db: Session, user: User, dept_id: int) -> Membership | None:
    return db.scalar(select(Membership).where(
        Membership.user_id == user.id,
        Membership.dept_id == dept_id,
    ))

def require_team_manager(dept_id: int, team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if user.is_platform_admin:
        return user
    membership = get_membership(db, user, dept_id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this department")
    if membership.role == "admin":
        return user
    team = db.scalar(select(Team).where(Team.id == team_id, Team.dept_id == dept_id))
    if team and team.manager_user_id == user.id:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires a department admin, or the lead of this team",
    )

def require_dept_role(*roles: str):
    def _check(dept_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.is_platform_admin:
            return user
        membership = get_membership(db, user, dept_id)
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this department")
        if roles and membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires one of roles: {', '.join(roles)}")
        return user

    return _check

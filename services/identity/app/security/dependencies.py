from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, Team, User
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

def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """Runs the whole CypherCrescent workspace — creates departments, can
    administer any of them, and grants platform admin to others."""
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires a platform administrator")
    return user

def get_membership(db: Session, user: User, dept_id: int) -> Membership | None:
    return db.scalar(select(Membership).where(
        Membership.user_id == user.id,
        Membership.dept_id == dept_id,
        Membership.is_active.is_(True),
    ))

def require_team_manager(dept_id: int, team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Who may change a team's roster: department admins (any team), or the
    team's named lead (theirs only). Reads Team.manager_user_id rather than
    inferring from role+assignment, so there's one answer to "who runs this
    team" and it's the same one Pulse uses to route report approvals."""
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
    """`Dept_id` is read from the path, so permission is always
    evaluated against the department actually being acted on — a person can be
    an admin in one department and an engineer in another without either
    leaking into the other.

    Platform admins pass every check. Pass no roles to require membership only.

        admin_only = require_dept_role("admin")

        @router.patch("/departments/{dept_id}")
        def rename(dept_id: int, _=Depends(admin_only)): ..."""

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

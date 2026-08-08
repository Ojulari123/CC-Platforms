"""Platform administrators — the people who run CypherCrescent's workspace as a
whole (create departments, administer any of them, appoint other platform
admins). Distinct from the per-department "admin" role, which is scoped to one
department."""
from fastapi import HTTPException
from app.schemas.departments import UserAccountResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.models import Department, Team, User

def list_platform_admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_platform_admin.is_(True)).order_by(User.first_name, User.last_name)))

def list_users(db: Session, q: str | None, is_active: bool | None, limit: int, offset: int) -> tuple[list[User], int]:
    """Every account in the workspace, no department/team scoping — the platform
    admin's flat directory. Mirrors the department roster's pagination + name/email
    search so the two lists behave the same. `total` reflects the filters so the
    client can page within a filtered result set."""
    base = select(User)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(
            func.lower(User.first_name).like(like),
            func.lower(User.last_name).like(like),
            func.lower(User.email).like(like),
        ))
    if is_active is not None:
        base = base.where(User.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(base.subquery()))
    users = list(db.scalars(base.order_by(User.first_name, User.last_name).limit(limit).offset(offset)))
    return users, total or 0

def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def deactivate_user(db: Session, user_id: int, acting_user: User) -> UserAccountResponse:
    """Offboarding. The account survives (so reports, approvals and audit trails
    keep pointing at a real person) but the person can no longer log in, and
    every existing session dies immediately.

    Titles are deliberately NOT vacated. Deactivation is reversible and often
    temporary — long leave, a suspended account — and silently dismantling
    someone's teams on the way out would be worse than leaving them in place.
    The response lists what they still run so it's visible rather than silent;
    to hand those over properly, remove them from the department instead."""
    user = _get_user(db, user_id)
    # This alone prevents locking the workspace out: deactivating requires being
    # a platform admin, so the only person who could deactivate the last one is
    # that person. (A separate "is this the last admin" count would be
    # unreachable code — the self-check always fires first.)
    if user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    user.is_active = False
    db.commit()
    db.refresh(user)
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, user_id)
    return _account_response(db, user)

def reactivate_user(db: Session, user_id: int) -> UserAccountResponse:
    """Undo a deactivation. Memberships and titles were never touched, so they
    come back exactly as they were. They must log in again."""
    user = _get_user(db, user_id)
    user.is_active = True
    db.commit()
    db.refresh(user)
    return _account_response(db, user)

def _account_response(db: Session, user: User) -> UserAccountResponse:
    """Surfaces anything the person still runs, so deactivating someone who
    leads a team doesn't quietly leave it without a working lead."""
    led = db.execute(
        select(Team.name, Department.name)
        .join(Department, Department.id == Team.dept_id)
        .where(Team.manager_user_id == user.id)
    ).all()
    headed = db.scalars(select(Department.name).where(Department.head_user_id == user.id)).all()
    return UserAccountResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        still_leads=[f"{team} ({dept})" for team, dept in led],
        still_heads=list(headed),
    )

def grant_platform_admin(db: Session, user_id: int) -> User:
    user = _get_user(db, user_id)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Cannot promote a deactivated account")
    user.is_platform_admin = True
    db.commit()
    db.refresh(user)
    # Their existing tokens still say is_platform_admin=false; force a re-issue.
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, user_id)
    return user

def revoke_platform_admin(db: Session, user_id: int) -> User:
    user = _get_user(db, user_id)
    remaining = db.scalar(
        select(func.count()).select_from(User).where(User.is_platform_admin.is_(True), User.id != user_id)
    )
    if not remaining:
        raise HTTPException(status_code=400, detail="Cannot remove the only platform administrator")
    user.is_platform_admin = False
    db.commit()
    db.refresh(user)
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, user_id)
    return user

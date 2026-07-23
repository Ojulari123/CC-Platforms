"""Platform administrators — the people who run CypherCrescent's workspace as a
whole (create departments, administer any of them, appoint other platform
admins). Distinct from the per-department "admin" role, which is scoped to one
department."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import User

def list_platform_admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_platform_admin.is_(True)).order_by(User.first_name, User.last_name)))

def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

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

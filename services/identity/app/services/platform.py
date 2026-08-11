from fastapi import HTTPException
from app.schemas.departments import UserAccountResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.models import Department, Invite, Membership, PasswordResetToken, Team, User

def list_platform_admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_platform_admin.is_(True)).order_by(User.first_name, User.last_name)))

def list_users(db: Session, q: str | None, is_active: bool | None, limit: int, offset: int) -> tuple[list[User], int]:
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
    user = _get_user(db, user_id)
    # Also why the workspace can't be locked out: only a platform admin can
    # deactivate, so the only account that could take out the last one is its own.
    if user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    user.is_active = False
    db.commit()
    db.refresh(user)
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, user_id)
    return _account_response(db, user)

def reactivate_user(db: Session, user_id: int) -> UserAccountResponse:
    user = _get_user(db, user_id)
    user.is_active = True
    db.commit()
    db.refresh(user)
    return _account_response(db, user)

_DEACTIVATE_INSTEAD = "Deactivate it instead: that keeps their name on anything they've already done in other products."

def _history_reason(db: Session, user: User) -> str | None:
    """remove_member deletes the membership row, so a live count can't see an
    ex-member. README "Why users.onboarded_at exists" has the rest."""
    if user.onboarded_at:
        return "they have been part of a department"
    if user.email_verified:
        return "they joined a department by accepting an emailed invite"
    if db.scalar(select(func.count()).select_from(Invite).where(Invite.email == user.email, Invite.accepted_at.is_not(None))):
        return "they have accepted a department invite before"
    return None

def delete_user(db: Session, user_id: int, acting_user: User) -> None:
    """Identity can't ask Pulse whether this person authored anything, so every guard
    below errs towards refusing."""
    user = _get_user(db, user_id)
    if user.id == acting_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    # Also covers "the last platform admin": demoting is always the first step, and
    # revoke_platform_admin refuses to demote the only one.
    if user.is_platform_admin:
        raise HTTPException(status_code=400, detail="Cannot delete a platform administrator; revoke their platform admin role first")

    memberships = db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user_id))
    if memberships:
        raise HTTPException(
            status_code=400,
            detail=f"That account belongs to {memberships} department(s). Remove them from those first. {_DEACTIVATE_INSTEAD}",
        )

    # The FKs for these are ON DELETE SET NULL, so a delete would quietly vacate
    # a team lead or a department head rather than being refused.
    led = db.scalars(select(Team.name).where(Team.manager_user_id == user_id)).all()
    headed = db.scalars(select(Department.name).where(Department.head_user_id == user_id)).all()
    if led or headed:
        runs = [f"leads {name}" for name in led] + [f"heads {name}" for name in headed]
        raise HTTPException(
            status_code=400,
            detail=f"That account still {' and '.join(runs)}. Hand that over first. {_DEACTIVATE_INSTEAD}",
        )

    reason = _history_reason(db, user)
    if reason:
        raise HTTPException(status_code=400, detail=f"That account cannot be deleted because {reason}. {_DEACTIVATE_INSTEAD}")

    # Neither table has a relationship on User, so the ORM would leave them behind;
    # done here because SQLite doesn't enforce FKs by default. The invite survives
    # with no named inviter, since someone else is waiting on that link.
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).delete(synchronize_session=False)
    db.query(Invite).filter(Invite.invited_by == user_id).update({"invited_by": None}, synchronize_session=False)
    db.delete(user)
    db.commit()

def _account_response(db: Session, user: User) -> UserAccountResponse:
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

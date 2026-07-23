from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, Department, User
from app.schemas.auth import ProfileUpdate, UserMeResponse
from app.security import get_current_user

router = APIRouter(tags=["me"])

def _me_response(db: Session, user: User) -> UserMeResponse:
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    department = db.get(Department, membership.dept_id) if membership else None
    return UserMeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified,
        is_active=user.is_active,
        created_at=user.created_at,
        active_dept_id=membership.dept_id if membership else None,
        active_dept_name=department.name if department else None,
        active_role=membership.role if membership else None,
    )

@router.get("/me", response_model=UserMeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    """Return the caller's identity + their currently active department/role.
    Everything here comes from identity's own DB — no cross-service reads."""
    return _me_response(db, user)

@router.patch("/me", response_model=UserMeResponse)
def update_me(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    """Update your own profile. Role and department aren't here on purpose —
    those are an admin's call, via /dept/members/{id}."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return _me_response(db, user)

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Department, Membership, Team, User
from app.schemas.auth import MembershipResponse, ProfileUpdate, UserMeResponse
from app.security import get_current_user

router = APIRouter(tags=["me"])

def _me_response(db: Session, user: User) -> UserMeResponse:
    rows = db.execute(
        select(Membership, Department, Team)
        .join(Department, Department.id == Membership.dept_id)
        .outerjoin(Team, Team.id == Membership.team_id)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True))
        .order_by(Department.name)
    ).all()
    return UserMeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        created_at=user.created_at,
        memberships=[
            MembershipResponse(
                dept_id=m.dept_id,
                dept_name=d.name,
                team_id=m.team_id,
                team_name=t.name if t else None,
                role=m.role,
            )
            for m, d, t in rows
        ],
    )

@router.get("/me", response_model=UserMeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    """The caller's identity plus every department they belong to.
    All from identity's own DB — no cross-service reads."""
    return _me_response(db, user)

@router.patch("/me", response_model=UserMeResponse)
def update_me(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    """Update your own profile. Role and department aren't here on purpose —
    those are an admin's call, via /departments/{id}/members/{id}."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return _me_response(db, user)

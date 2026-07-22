from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, Org, User
from app.schemas.auth import UserMeResponse
from app.security import get_current_user

router = APIRouter(tags=["me"])

@router.get("/me", response_model=UserMeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    """Return the caller's identity + their currently active org/role.
    Everything here comes from identity's own DB — no cross-service reads."""
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    org = db.get(Org, membership.org_id) if membership else None
    return UserMeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified,
        is_active=user.is_active,
        created_at=user.created_at,
        active_org_id=membership.org_id if membership else None,
        active_org_name=org.name if org else None,
        active_role=membership.role if membership else None,
    )

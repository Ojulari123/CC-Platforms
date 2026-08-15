from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Department, Membership, Team, User
from app.schemas.auth import MembershipResponse, ProfileUpdate, SessionResponse, UserMeResponse
from app.security import get_current_user, get_token_payload
from app.security.jwt import TokenPayload
from app.services import auth as auth_service

router = APIRouter(tags=["me"])

def _me_response(db: Session, user: User) -> UserMeResponse:
    rows = db.execute(
        select(Membership, Department, Team)
        .join(Department, Department.id == Membership.dept_id)
        .outerjoin(Team, Team.id == Membership.team_id)
        .where(Membership.user_id == user.id)
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
    return _me_response(db, user)

@router.patch("/me", response_model=UserMeResponse)
def update_me(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserMeResponse:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return _me_response(db, user)

@router.get("/me/sessions", response_model=list[SessionResponse])
def my_sessions(token: TokenPayload = Depends(get_token_payload), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SessionResponse]:
    return auth_service.list_sessions(db, user.id, token.session_id)

@router.delete("/me/sessions/current", status_code=status.HTTP_204_NO_CONTENT)
def end_current_session(token: TokenPayload = Depends(get_token_payload), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Sign out this device. A product only ever holds an access token, so it names its
    own session through the sid claim rather than by sending a refresh token it has
    never seen."""
    if not token.session_id:
        raise HTTPException(status_code=400, detail="This access token doesn't name a session; use /auth/logout-all")
    auth_service.revoke_session(db, user.id, token.session_id)

@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Sign out one of the caller's other devices, listed by GET /me/sessions. Anything
    that isn't one of theirs is a 404, including a session that exists but belongs to
    someone else: a 403 there would confirm whose it is."""
    auth_service.revoke_session(db, user.id, session_id)

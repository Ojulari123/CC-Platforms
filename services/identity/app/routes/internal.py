from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.oauth import EmailLookupRequest, EmailLookupResponse, ProfileLookupRequest, ProfileLookupResponse, TokenVersionLookupRequest, TokenVersionLookupResponse, UserEmail, UserProfile, UserTokenVersion
from app.security import require_service_scope

router = APIRouter(prefix="/internal", tags=["internal"])

_emails_reader = require_service_scope("users:read:email")
_profiles_reader = require_service_scope("users:read:profile")
_token_version_reader = require_service_scope("tokens:verify")

@router.post("/users/emails", response_model=EmailLookupResponse)
def lookup_emails(payload: EmailLookupRequest, _=Depends(_emails_reader), db: Session = Depends(get_db)) -> EmailLookupResponse:
    """Unknown ids are omitted so a partial list still succeeds. No unknown_user_ids
    counterpart — the only consumer emails people, and has no cleanup decision
    riding on it."""
    if not payload.user_ids:
        return EmailLookupResponse(users=[])
    rows = db.execute(select(User.id, User.email).where(User.id.in_(payload.user_ids))).all()
    return EmailLookupResponse(users=[UserEmail(user_id=uid, email=email) for uid, email in rows])

@router.post("/users/profiles", response_model=ProfileLookupResponse)
def lookup_profiles(payload: ProfileLookupRequest, _=Depends(_profiles_reader), db: Session = Depends(get_db)) -> ProfileLookupResponse:
    if not payload.user_ids:
        return ProfileLookupResponse(users=[], unknown_user_ids=[])
    rows = db.execute(
        select(User.id, User.first_name, User.last_name, User.avatar_url, User.is_active)
        .where(User.id.in_(payload.user_ids)).order_by(User.id)
    ).all()
    found = {uid for uid, *_ in rows}
    return ProfileLookupResponse(
        users=[
            UserProfile(user_id=uid, first_name=first, last_name=last, avatar_url=avatar, is_active=active)
            for uid, first, last, avatar, active in rows
        ],
        unknown_user_ids=sorted(set(payload.user_ids) - found),
    )

@router.post("/users/token-versions", response_model=TokenVersionLookupResponse)
def lookup_token_versions(payload: TokenVersionLookupRequest, _=Depends(_token_version_reader), db: Session = Depends(get_db)) -> TokenVersionLookupResponse:
    if not payload.user_ids:
        return TokenVersionLookupResponse(users=[], unknown_user_ids=[])
    rows = db.execute(
        select(User.id, User.token_version).where(User.id.in_(payload.user_ids)).order_by(User.id)
    ).all()
    found = {uid for uid, _ in rows}
    return TokenVersionLookupResponse(
        users=[UserTokenVersion(user_id=uid, token_version=tv) for uid, tv in rows],
        unknown_user_ids=sorted(set(payload.user_ids) - found),
    )

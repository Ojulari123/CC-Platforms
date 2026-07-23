"""Invite flow — how anyone after the founder joins a department.

create: admin sends an invite → email with one-time link (raw token never stored).
accept: recipient proves control of the email by presenting the token. New
users set a password and get an account (email_verified=True — they clicked a
link sent to that address); existing users just gain a membership. Both get a
fresh token pair scoped to the inviting department."""
import hashlib, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Invite, Membership, Department, Team, User
from app.schemas.auth import TokenPair
from app.schemas.departments import InviteAccept, InviteCreate
from app.services import email as email_service
from app.services.auth import _build_pair_response, _issue_token_pair
from app.security import hash_password, validate_password

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_invite(db: Session, dept_id: int, inviter: User, payload: InviteCreate) -> Invite:
    department = db.get(Department, dept_id)
    invited_email = payload.email.lower()

    existing_user = db.scalar(select(User).where(User.email == invited_email))
    if existing_user and db.scalar(select(Membership).where(Membership.user_id == existing_user.id, Membership.dept_id == dept_id)):
        raise HTTPException(status_code=400, detail="That person is already a member of this department")

    if payload.team_id is not None:
        if not db.scalar(select(Team).where(Team.id == payload.team_id, Team.dept_id == dept_id)):
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

    # One live invite per (department, email) — replace any pending one.
    for old in db.scalars(select(Invite).where(Invite.dept_id == dept_id, Invite.email == invited_email, Invite.accepted_at.is_(None))):
        db.delete(old)

    raw_token = secrets.token_urlsafe(32)
    invite = Invite(
        dept_id=dept_id,
        email=invited_email,
        role=payload.role,
        team_id=payload.team_id,
        token_hash=_hash_token(raw_token),
        invited_by=inviter.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    db.flush()

    try:
        email_service.send_invite(to=invited_email, dept_name=department.name, role=payload.role, raw_token=raw_token)
    except email_service.EmailNotConfigured:
        raise HTTPException(status_code=503, detail="Email is not configured on the server (BREVO_API_KEY / EMAIL_FROM)")
    except email_service.EmailSendError:
        raise HTTPException(status_code=502, detail="Could not send the invite email — invite not created, try again")

    # Commit only after the email went out, so a failed send leaves no orphan invite.
    db.commit()
    db.refresh(invite)
    return invite

def accept_invite(db: Session, payload: InviteAccept) -> TokenPair:
    invite = db.scalar(select(Invite).where(Invite.token_hash == _hash_token(payload.token)))
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid invite link")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="This invite has already been used")
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This invite has expired — ask for a new one")

    user = db.scalar(select(User).where(User.email == invite.email))
    if user is None:
        if not (payload.first_name and payload.last_name and payload.password):
            raise HTTPException(status_code=400, detail="first_name, last_name and password are required to create your account")
        validate_password(payload.password)
        user = User(
            email=invite.email,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            email_verified=True,  # they proved control of the address by opening the link
        )
        db.add(user)
        db.flush()
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    membership = Membership(user_id=user.id, dept_id=invite.dept_id, team_id=invite.team_id, role=invite.role)
    db.add(membership)
    db.flush()

    invite.accepted_at = datetime.now(timezone.utc)
    access, refresh = _issue_token_pair(db, user, membership)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

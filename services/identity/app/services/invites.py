"""Only the hash of the emailed token is stored; presenting it proves control of
the address, which is why accepting sets email_verified."""
import hashlib, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Invite, Membership, Department, Team, User
from app.schemas.auth import TokenPair
from app.schemas.departments import InviteAccept, InviteCreate, InvitePreview
from app.services import email as email_service
from app.services.auth import _build_pair_response, _issue_token_pair, bump_token_version
from app.security import hash_password, validate_password

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_invite(db: Session, dept_id: int, inviter: User, payload: InviteCreate) -> Invite:
    # A platform admin passes the dept_id guard without a membership lookup, so nothing upstream has proved the department exists.
    department = db.get(Department, dept_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    invited_email = payload.email.lower()

    existing_user = db.scalar(select(User).where(User.email == invited_email))
    if existing_user and db.scalar(select(Membership).where(Membership.user_id == existing_user.id, Membership.dept_id == dept_id)):
        raise HTTPException(status_code=400, detail="That person is already a member of this department")

    team = None
    if payload.team_id is not None:
        team = db.scalar(select(Team).where(Team.id == payload.team_id, Team.dept_id == dept_id))
        if not team:
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

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
        email_service.send_invite(
            to=invited_email,
            dept_name=department.name,
            team_name=team.name if team else None,
            role=payload.role,
            raw_token=raw_token,
        )
    except email_service.EmailNotConfigured:
        raise HTTPException(status_code=503, detail="Email is not configured on the server (BREVO_API_KEY / EMAIL_FROM)")
    except email_service.EmailSendError:
        raise HTTPException(status_code=502, detail="Could not send the invite email, so the invite was not created. Try again")

    # Commit only after the email went out, so a failed send leaves no orphan invite.
    db.commit()
    db.refresh(invite)
    return invite

def list_pending_invites(db: Session, dept_id: int) -> list[Invite]:
    """Expired invites are included on purpose: an admin needs to see a dead invite
    to know why someone never got in."""
    return list(db.scalars(
        select(Invite).where(Invite.dept_id == dept_id, Invite.accepted_at.is_(None)).order_by(Invite.created_at.desc())
    ))

def revoke_invite(db: Session, dept_id: int, invite_id: int) -> None:
    invite = db.scalar(select(Invite).where(Invite.id == invite_id, Invite.dept_id == dept_id))
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found in this department")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="That invite was already accepted; remove the member instead")
    db.delete(invite)
    db.commit()

def _load_valid_invite(db: Session, raw_token: str) -> Invite:
    invite = db.scalar(select(Invite).where(Invite.token_hash == _hash_token(raw_token)))
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid invite link")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="This invite has already been used")
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This invite has expired, so ask for a new one")
    return invite

def preview_invite(db: Session, raw_token: str) -> InvitePreview:
    invite = _load_valid_invite(db, raw_token)
    department = db.get(Department, invite.dept_id)
    team = db.get(Team, invite.team_id) if invite.team_id else None
    existing_user = db.scalar(select(User).where(User.email == invite.email))
    inviter = db.get(User, invite.invited_by) if invite.invited_by else None
    return InvitePreview(
        email=invite.email,
        dept_name=department.name if department else "",
        team_name=team.name if team else None,
        role=invite.role,
        needs_account=existing_user is None,
        invited_by_name=f"{inviter.first_name} {inviter.last_name}" if inviter and inviter.is_active else None,
        expires_at=invite.expires_at,
    )

def accept_invite(db: Session, payload: InviteAccept) -> TokenPair:
    invite = _load_valid_invite(db, payload.token)

    user = db.scalar(select(User).where(User.email == invite.email))
    had_account = user is not None
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

    # A stale invite or a double-submit still reaches here; without this the insert
    # trips uq_membership_user_dept and surfaces as a 500 instead of a 409. The
    # try/except below covers the concurrent race the pre-check can't.
    already_member = db.scalar(select(Membership).where(
        Membership.user_id == user.id, Membership.dept_id == invite.dept_id
    ))
    if already_member:
        raise HTTPException(status_code=409, detail="You're already a member of this department.")

    db.add(Membership(user_id=user.id, dept_id=invite.dept_id, team_id=invite.team_id, role=invite.role))
    if user.onboarded_at is None:
        user.onboarded_at = datetime.now(timezone.utc)
    invite.accepted_at = datetime.now(timezone.utc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You're already a member of this department.")

    # An existing account can accept an invite to a second department, and its other
    # sessions are holding tokens that don't know about it. Bumped *before* the pair is
    # minted so the one handed back below carries the new version and stays valid. An
    # account created right here has no other sessions, so bumping it would be churn.
    if had_account:
        bump_token_version(db, user.id)
    access, refresh = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

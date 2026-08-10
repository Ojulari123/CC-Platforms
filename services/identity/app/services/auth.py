import hashlib, re, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Membership, Department, PasswordResetToken, RefreshToken, Team, User
from app.schemas.auth import RegisterRequest, SignupRequest, TokenPair, UserResponse
from app.security import create_access_token, hash_password, validate_password, verify_password
from app.services import email as email_service

# dummy verify so unknown emails aren't faster — no enumeration
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))

def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "department"

def _unique_dept_slug(db: Session, base: str) -> str:
    slug = base
    n = 1
    while db.scalar(select(Department).where(Department.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def _membership_claims(db: Session, user_id: int) -> list[dict]:
    rows = db.scalars(select(Membership).where(Membership.user_id == user_id))
    return [{"dept_id": m.dept_id, "team_id": m.team_id, "role": m.role} for m in rows]

def _led_team_ids(db: Session, user_id: int) -> list[int]:
    return list(db.scalars(select(Team.id).where(Team.manager_user_id == user_id)))

def _issue_token_pair(db: Session, user: User, family_id: str | None = None) -> tuple[str, str]:
    access = create_access_token(
        user_id=user.id,
        email=user.email,
        memberships=_membership_claims(db, user.id),
        is_platform_admin=user.is_platform_admin,
        token_version=user.token_version,
        leads=_led_team_ids(db, user.id),
    )
    raw_refresh = secrets.token_urlsafe(64)
    db.add(RefreshToken(
        token_hash=_hash_refresh(raw_refresh),
        user_id=user.id,
        family_id=family_id or secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    return access, raw_refresh

def _build_pair_response(access: str, refresh: str, user: User) -> TokenPair:
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )

def register_user(db: Session, payload: RegisterRequest) -> TokenPair:
    """Bootstrap only, and the gate is a *platform admin* existing, not any user —
    signup_user creates plain accounts, and closing on those would brick this."""
    if db.scalar(select(User.id).where(User.is_platform_admin.is_(True)).limit(1)) is not None:
        raise HTTPException(
            status_code=403,
            detail="Registration is closed. Ask an admin to invite you.",
        )

    validate_password(payload.password)

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        is_platform_admin=True,
    )
    db.add(user)
    db.flush()

    department = Department(name=payload.dept_name, slug=_unique_dept_slug(db, _slugify(payload.dept_name)))
    db.add(department)
    db.flush()

    db.add(Membership(user_id=user.id, dept_id=department.id, role="admin"))
    user.onboarded_at = datetime.now(timezone.utc)
    db.flush()

    access, refresh = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

def signup_user(db: Session, payload: SignupRequest) -> TokenPair:
    domains = settings.signup_allowed_domains_list
    if domains:
        # Empty list = open to everyone; a set list locks signup to the org.
        domain = payload.email.rsplit("@", 1)[-1].lower()
        if domain not in domains:
            raise HTTPException(status_code=403, detail="Sign-ups aren't open to that email domain")

    if db.scalar(select(User.id).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    validate_password(payload.password)

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        # Email verification is deferred to a later flow — signing up doesn't
        # prove control of the address the way accepting an emailed invite does.
        email_verified=False,
    )
    db.add(user)
    db.flush()

    access, refresh = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

def request_password_reset(db: Session, email: str) -> None:
    if not email_service.is_configured():
        raise HTTPException(status_code=503, detail="Email is not configured on the server (BREVO_API_KEY / EMAIL_FROM)")

    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active:
        return  # silent no-op — no account enumeration

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).delete(synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_refresh(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
    ))
    db.commit()

    try:
        email_service.send_password_reset(to=user.email, raw_token=raw_token)
    except email_service.EmailSendError:
        # Never surface a transport failure to the caller — it would leak that
        # this address has an account. Logged inside the email layer; the token
        # just goes unused and expires.
        pass

def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_refresh(raw_token)))
    if not row or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset link")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired — request a new one")

    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset link")

    validate_password(new_password)

    user.password_hash = hash_password(new_password)
    row.used_at = datetime.now(timezone.utc)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)
    ).update({"is_revoked": True}, synchronize_session=False)
    user.token_version = user.token_version + 1
    db.commit()

def login_user(db: Session, email: str, password: str) -> TokenPair:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user:
        verify_password(password, _DUMMY_PASSWORD_HASH)  # burn the same time as a wrong-password check
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    access, refresh = _issue_token_pair(db, user)
    db.commit()
    return _build_pair_response(access, refresh, user)

def rotate_refresh_token(db: Session, raw_token: str) -> TokenPair:
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_token)))
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.is_revoked:
        # Killing the family only stops new pairs; bump token_version so the stolen
        # access token dies too. That is per-user, so it signs them out everywhere —
        # the right trade on a theft signal. See README "What revokes what".
        db.query(RefreshToken).filter(RefreshToken.family_id == stored.family_id).update({"is_revoked": True}, synchronize_session=False)
        user = db.get(User, stored.user_id)
        if user:
            user.token_version = user.token_version + 1
        db.commit()
        raise HTTPException(status_code=401, detail="Token reuse detected. All sessions revoked. Please log in again.")

    stored_exp = stored.expires_at
    if stored_exp.tzinfo is None:
        stored_exp = stored_exp.replace(tzinfo=timezone.utc)
    if stored_exp < datetime.now(timezone.utc):
        stored.is_revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired. Please log in again.")

    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        stored.is_revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="User not available")

    stored.is_revoked = True
    access, new_refresh = _issue_token_pair(db, user, family_id=stored.family_id)
    stored.replaced_by = _hash_refresh(new_refresh)
    db.commit()
    return _build_pair_response(access, new_refresh, user)

def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Deliberately does NOT bump token_version — that is per-user, so it would sign
    them out everywhere. Use logout-all to cut the live access token now."""
    db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_refresh(raw_token)).update({"is_revoked": True}, synchronize_session=False)
    db.commit()

def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)).update({"is_revoked": True}, synchronize_session=False)
    user = db.get(User, user_id)
    if user:
        user.token_version = user.token_version + 1
    db.commit()

def change_password(db: Session, user: User, current_password: str, new_password: str) -> TokenPair:
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    validate_password(new_password)

    user.password_hash = hash_password(new_password)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)).update({"is_revoked": True}, synchronize_session=False)
    user.token_version = user.token_version + 1
    db.flush()

    access, refresh = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

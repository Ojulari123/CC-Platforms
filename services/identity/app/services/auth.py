import hashlib, re, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import EmailChangeToken, Membership, Department, PasswordResetToken, RefreshToken, Team, User
from app.schemas.auth import RegisterRequest, SessionResponse, SignupRequest, TokenPair, UserResponse
from app.security import create_access_token, hash_password, validate_password, verify_password
from app import revocations
from app.services import email as email_service

# dummy verify so unknown emails aren't faster, which would allow enumeration
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))

def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def session_id_for_family(family_id: str) -> str:
    """family_id is random and lives in the database; this one-way digest is what
    leaves the service, in the access token and in /me/sessions."""
    return hashlib.sha256(family_id.encode()).hexdigest()[:32]

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
    family = family_id or secrets.token_urlsafe(32)
    access = create_access_token(
        user_id=user.id,
        email=user.email,
        memberships=_membership_claims(db, user.id),
        is_platform_admin=user.is_platform_admin,
        token_version=user.token_version,
        leads=_led_team_ids(db, user.id),
        session_id=session_id_for_family(family),
    )
    raw_refresh = secrets.token_urlsafe(64)
    db.add(RefreshToken(
        token_hash=_hash_refresh(raw_refresh),
        user_id=user.id,
        family_id=family,
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
    """Bootstrap only, and the gate is a *platform admin* existing, not any user:
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

    # Only reachable if departments outlived every platform admin, but the name index
    # would answer that with a 500 otherwise.
    if db.scalar(select(Department).where(func.lower(Department.name) == payload.dept_name.lower())):
        raise HTTPException(status_code=409, detail="A department with that name already exists")

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
        # Email verification is deferred to a later flow, since signing up doesn't
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
        return  # silent no-op, so no account enumeration

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
        # Never surface a transport failure to the caller: it would leak that
        # this address has an account. Logged inside the email layer; the token
        # just goes unused and expires.
        pass

def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_refresh(raw_token)))
    if not row or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset link")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired, so request a new one")

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
    revocations.publish_user_revoked(user.id, user.token_version)

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

    if stored.is_revoked and stored.replaced_by is None:
        # Revoked but never rotated away, so the family was ended deliberately — a
        # logout, a per-device sign-out, or an expiry burn — not replayed by someone
        # holding a copy. Without this branch the signed-out device's next scheduled
        # refresh would read as theft and bump token_version, turning "sign out my
        # phone" into "sign out everywhere" within minutes.
        raise HTTPException(status_code=401, detail="Session ended. Please log in again.")

    if stored.is_revoked:
        # Rotated away and presented again: two parties hold this token. Killing the
        # family only stops new pairs; bump token_version so the stolen access token
        # dies too. That is per-user, so it signs them out everywhere, the right trade
        # on a theft signal. See README "What revokes what".
        db.query(RefreshToken).filter(RefreshToken.family_id == stored.family_id).update({"is_revoked": True}, synchronize_session=False)
        user = db.get(User, stored.user_id)
        if user:
            user.token_version = user.token_version + 1
        db.commit()
        if user:
            revocations.publish_user_revoked(user.id, user.token_version)
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
    """Deliberately does NOT bump token_version, which is per-user, so it would sign
    them out everywhere. Use logout-all to cut the live access token now."""
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_token)))
    if not stored:
        return  # unknown token: still a 204, so this can't be used to probe for live ones
    db.query(RefreshToken).filter(RefreshToken.token_hash == stored.token_hash).update({"is_revoked": True}, synchronize_session=False)
    db.commit()
    revocations.publish_session_revoked(session_id_for_family(stored.family_id))

def _family_for_session(db: Session, user_id: int, session_id: str) -> str | None:
    """session_id is a truncated digest of family_id and only family_id is stored, so the
    match is made by re-digesting. The scan is always narrowed to one user first — a
    handful of rows behind the user_id index — which is also the rule that stops anyone
    naming somebody else's session. A stored digest column would buy nothing here (no
    lookup is ever cross-user) and would be one more derived value to keep in step."""
    families = db.scalars(select(RefreshToken.family_id).where(RefreshToken.user_id == user_id).distinct())
    for family_id in families:
        if session_id_for_family(family_id) == session_id:
            return family_id
    return None

def revoke_session(db: Session, user_id: int, session_id: str) -> None:
    """One device, not the account: deliberately does NOT bump token_version, which is
    the account-wide lever and would sign the person out of every other session too.
    Access tokens already minted from this family stay valid until they expire
    (ACCESS_TOKEN_EXPIRE_MINUTES); what ends now is the ability to mint more."""
    family_id = _family_for_session(db, user_id, session_id)
    if family_id is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Re-running on an already-revoked family updates nothing and still answers 204.
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.family_id == family_id, RefreshToken.is_revoked.is_(False)
    ).update({"is_revoked": True}, synchronize_session=False)
    db.commit()
    revocations.publish_session_revoked(session_id_for_family(family_id))

def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)).update({"is_revoked": True}, synchronize_session=False)
    user = db.get(User, user_id)
    if user:
        user.token_version = user.token_version + 1
    db.commit()
    if user:
        revocations.publish_user_revoked(user_id, user.token_version)

def bump_token_version(db: Session, *user_ids: int | None) -> None:
    """Their claims changed, so every access token already out there is asserting the old
    ones. Bumping token_version makes get_current_user reject those within seconds, and
    the refresh tokens are deliberately left alone — rotate_refresh_token never reads
    token_version — so the client's next scheduled refresh quietly mints a token with the
    corrected claims. Nobody is signed out; their permissions just catch up.

    That is the whole difference from revoke_all_for_user, which kills the refresh tokens
    too and does sign them out of every device. Use this for authorisation changes and
    that one for "this account or credential is no longer trusted".

    Call it once the change is committed, so anything re-issued reads the new state."""
    bumped = []
    for user_id in dict.fromkeys(uid for uid in user_ids if uid is not None):
        user = db.get(User, user_id)
        if user is None:
            continue
        user.token_version = user.token_version + 1
        bumped.append(user)
    if not bumped:
        return
    db.commit()
    for user in bumped:
        revocations.publish_user_revoked(user.id, user.token_version)

def list_sessions(db: Session, user_id: int, current_session_id: str | None = None) -> list[SessionResponse]:
    """One row per refresh-token family, since rotation replaces the token but not the
    session. A family is only dead once nothing in it is still live."""
    rows = db.execute(
        select(
            RefreshToken.family_id,
            func.min(RefreshToken.created_at),
            func.max(RefreshToken.created_at),
            func.count(RefreshToken.id),
            func.max(RefreshToken.expires_at),
            func.sum(case((RefreshToken.is_revoked.is_(False), 1), else_=0)),
        )
        .where(RefreshToken.user_id == user_id)
        .group_by(RefreshToken.family_id)
        .order_by(func.max(RefreshToken.created_at).desc(), func.max(RefreshToken.id).desc())
    ).all()
    out = []
    for family_id, started_at, last_used_at, token_count, expires_at, live_count in rows:
        session_id = session_id_for_family(family_id)
        out.append(SessionResponse(
            session_id=session_id,
            started_at=started_at,
            last_used_at=last_used_at,
            rotations=token_count - 1,
            expires_at=expires_at,
            is_revoked=live_count == 0,
            is_current=session_id == current_session_id,
        ))
    return out

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
    revocations.publish_user_revoked(user.id, user.token_version)
    return _build_pair_response(access, refresh, user)

def request_email_change(db: Session, user: User, new_email: str, current_password: str) -> None:
    """The password check is the point: the email is the login identifier, so a stolen
    session alone must not be enough to move it."""
    if not email_service.is_configured():
        raise HTTPException(status_code=503, detail="Email is not configured on the server (BREVO_API_KEY / EMAIL_FROM)")

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    address = new_email.strip().lower()
    if address == user.email:
        raise HTTPException(status_code=400, detail="That's already the email on this account")

    db.query(EmailChangeToken).filter(
        EmailChangeToken.user_id == user.id, EmailChangeToken.used_at.is_(None)
    ).delete(synchronize_session=False)
    db.commit()

    if db.scalar(select(User.id).where(User.email == address)) is not None:
        # Says so outright, matching signup. This is a poor enumeration oracle — it is
        # authenticated, re-authed with the password and rate limited — and the silent
        # 204 it replaces told people to check an inbox no mail would ever arrive in.
        # Any pending link is already gone above.
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    raw_token = secrets.token_urlsafe(32)
    db.add(EmailChangeToken(
        user_id=user.id,
        new_email=address,
        token_hash=_hash_refresh(raw_token),
        user_token_version=user.token_version,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.EMAIL_CHANGE_EXPIRE_MINUTES),
    ))
    old_email = user.email
    db.commit()

    try:
        email_service.send_email_change_verification(to=address, raw_token=raw_token)
    except email_service.EmailSendError:
        pass  # logged in the email layer; the token just goes unused and expires

    try:
        email_service.send_email_change_notice(to=old_email, new_email=address)
    except email_service.EmailSendError:
        pass

def confirm_email_change(db: Session, raw_token: str) -> None:
    row = db.scalar(select(EmailChangeToken).where(EmailChangeToken.token_hash == _hash_refresh(raw_token)))
    if not row or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used confirmation link")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This confirmation link has expired, so request the change again")

    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid or already-used confirmation link")
    if user.token_version != row.user_token_version:
        # A password change or a sign-out-everywhere happened after the link was sent.
        # That is exactly how someone shuts down a request they didn't make, so the link
        # dies with it even though it is sitting in the other mailbox.
        raise HTTPException(status_code=400, detail="Invalid or already-used confirmation link")

    if db.scalar(select(User.id).where(User.email == row.new_email, User.id != user.id)) is not None:
        # Only reachable if the address was claimed between request and confirm. Whoever
        # holds this link already controls that mailbox, so saying so leaks nothing.
        row.used_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=409, detail="That email address is no longer available")

    user.email = row.new_email
    # Confirming the link is proof of control of the address, which signup never had.
    user.email_verified = True
    row.used_at = datetime.now(timezone.utc)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)
    ).update({"is_revoked": True}, synchronize_session=False)
    user.token_version = user.token_version + 1
    db.commit()
    revocations.publish_user_revoked(user.id, user.token_version)

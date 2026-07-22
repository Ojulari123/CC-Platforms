import hashlib, re, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Membership, Org, RefreshToken, User
from app.schemas.auth import RegisterRequest, TokenPair, UserResponse
from app.security import create_access_token, hash_password, validate_password, verify_password

def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"

def _unique_org_slug(db: Session, base: str) -> str:
    slug = base
    n = 1
    while db.scalar(select(Org).where(Org.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def _issue_token_pair(db: Session, user: User, membership: Membership | None, family_id: str | None = None) -> tuple[str, str]:
    """Create an access + refresh pair. Returns (access_token, raw_refresh_token).
    Stores only the SHA-256 hash of the refresh token."""
    access = create_access_token(
        user_id=user.id,
        email=user.email,
        org_id=membership.org_id if membership else None,
        role=membership.role if membership else None,
        token_version=user.token_version,
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
    validate_password(payload.password)

    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(user)
    db.flush()

    org = Org(name=payload.org_name, slug=_unique_org_slug(db, _slugify(payload.org_name)))
    db.add(org)
    db.flush()

    membership = Membership(user_id=user.id, org_id=org.id, role="admin")
    db.add(membership)
    db.flush()

    access, refresh = _issue_token_pair(db, user, membership)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

def login_user(db: Session, email: str, password: str) -> TokenPair:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    access, refresh = _issue_token_pair(db, user, membership)
    db.commit()
    return _build_pair_response(access, refresh, user)

def rotate_refresh_token(db: Session, raw_token: str) -> TokenPair:
    """Validate the presented refresh token, revoke it, and issue a new pair.
    Presenting a revoked token nukes the entire family — every session spawned
    from the same login is invalidated (stolen-token detection)."""
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_token)))
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.is_revoked:
        db.query(RefreshToken).filter(RefreshToken.family_id == stored.family_id).update({"is_revoked": True}, synchronize_session=False)
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

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))

    stored.is_revoked = True
    access, new_refresh = _issue_token_pair(db, user, membership, family_id=stored.family_id)
    stored.replaced_by = _hash_refresh(new_refresh)
    db.commit()
    return _build_pair_response(access, new_refresh, user)

def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Single-token logout. Idempotent — unknown tokens are silently ignored."""
    db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_refresh(raw_token)).update({"is_revoked": True}, synchronize_session=False)
    db.commit()

def revoke_all_for_user(db: Session, user_id: int) -> None:
    """Logout-everywhere. Also bumps token_version so any still-valid access
    tokens are rejected on next check (via the tv claim)."""
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)).update({"is_revoked": True}, synchronize_session=False)
    user = db.get(User, user_id)
    if user:
        user.token_version = user.token_version + 1
    db.commit()

def change_password(db: Session, user: User, current_password: str, new_password: str) -> TokenPair:
    """Verify current password, set new one, bump tv, revoke all refresh tokens,
    then issue a fresh pair so the caller stays logged in on THIS device.
    Every other session (browser, mobile, other laptop) is now dead."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    validate_password(new_password)

    user.password_hash = hash_password(new_password)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)).update({"is_revoked": True}, synchronize_session=False)
    user.token_version = user.token_version + 1
    db.flush()

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True)))
    access, refresh = _issue_token_pair(db, user, membership)
    db.commit()
    db.refresh(user)
    return _build_pair_response(access, refresh, user)

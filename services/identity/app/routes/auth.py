from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.rate_limit import limiter
from app.schemas.auth import ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, ResetPasswordRequest, TokenPair
from app.security import get_current_user
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.register_user(db, payload)

@router.post("/login", response_model=TokenPair)
@limiter.limit("10/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.login_user(db, payload.email, payload.password)

@router.post("/refresh", response_model=TokenPair)
@limiter.limit("30/minute")
def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.rotate_refresh_token(db, payload.refresh_token)

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> None:
    auth_service.revoke_refresh_token(db, payload.refresh_token)

@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Sign out on every device. Revokes all refresh tokens and bumps
    token_version, so outstanding access tokens die at identity immediately
    (products verifying via packages/core still honour theirs until expiry —
    see the tv note in docs/backlog.md)."""
    auth_service.revoke_all_for_user(db, user.id)

@router.post("/change-password", response_model=TokenPair)
@limiter.limit("5/minute")
def change_password(request: Request, payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.change_password(db, user, payload.current_password, payload.new_password)

@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> None:
    """Public. Always 204 whether or not the address has an account, so the
    response can't be used to enumerate users. A 503 only means email is
    misconfigured on the server — and it fires the same way for every address."""
    auth_service.request_password_reset(db, payload.email)

@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> None:
    """Public — the emailed token is the credential. Sets the new password and
    logs the account out everywhere; the user then signs in fresh."""
    auth_service.reset_password(db, payload.token, payload.new_password)

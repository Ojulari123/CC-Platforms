from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.rate_limit import limiter, user_or_address_key
from app.schemas.auth import ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, ResetPasswordRequest, SignupRequest, TokenPair
from app.security import get_current_user
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.register_user(db, payload)

@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def signup(request: Request, payload: SignupRequest, db: Session = Depends(get_db)) -> TokenPair:
    """Open self-signup — creates an account with no department. Distinct from
    /register, which is bootstrap-only. An admin places the new user afterwards."""
    return auth_service.signup_user(db, payload)

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
    auth_service.revoke_all_for_user(db, user.id)

@router.post("/change-password", response_model=TokenPair)
@limiter.limit("5/minute", key_func=user_or_address_key)
def change_password(request: Request, payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.change_password(db, user, payload.current_password, payload.new_password)

@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> None:
    auth_service.request_password_reset(db, payload.email)

@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> None:
    auth_service.reset_password(db, payload.token, payload.new_password)

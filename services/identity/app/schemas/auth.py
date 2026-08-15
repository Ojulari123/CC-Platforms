from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    # Stripped before the length check, to match the unique department name index,
    # which only folds case.
    dept_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)

class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: str

class ConfirmEmailChangeRequest(BaseModel):
    token: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    email_verified: bool
    created_at: datetime

class MembershipResponse(BaseModel):
    dept_id: int
    dept_name: str
    team_id: int | None = None
    team_name: str | None = None
    role: str

class UserMeResponse(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    last_name: str
    avatar_url: str | None = None
    email_verified: bool
    is_active: bool
    is_platform_admin: bool = False
    created_at: datetime
    memberships: list[MembershipResponse] = []

class SessionResponse(BaseModel):
    # One login/device, not one token: a refresh-token family covers every rotation
    # of the same session. session_id is a digest of the family id, so it names the
    # row without handing back a value the database stores.
    session_id: str
    started_at: datetime
    last_used_at: datetime
    rotations: int
    expires_at: datetime
    is_revoked: bool
    is_current: bool

class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

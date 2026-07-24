from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    dept_name: str = Field(min_length=1, max_length=200)

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
    """/me — full identity view plus EVERY department the caller belongs to.

    Deliberately a list, not one "active" department: a person can be an admin
    in Engineering and an engineer in Data, and picking one for them silently
    locked them out of the other."""
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

class ProfileUpdate(BaseModel):
    """Fields a user may change about themselves. Email is deliberately absent —
    changing it would need re-verification, so it gets its own flow later."""
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access_token expiry
    user: UserResponse

from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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
    new_password: str = Field(min_length=8, max_length=128)

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    email_verified: bool
    created_at: datetime

class UserMeResponse(BaseModel):
    """/me — full identity view plus the caller's currently active department + role."""
    id: int
    email: EmailStr
    first_name: str
    last_name: str
    avatar_url: str | None = None
    email_verified: bool
    is_active: bool
    created_at: datetime
    active_dept_id: int | None = None
    active_dept_name: str | None = None
    active_role: str | None = None

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access_token expiry
    user: UserResponse

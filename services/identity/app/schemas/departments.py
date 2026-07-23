from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "manager", "engineer"]

class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str

class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dept_id: int
    name: str
    slug: str

class MemberResponse(BaseModel):
    user_id: int
    email: EmailStr
    first_name: str
    last_name: str
    role: str
    team_id: int | None
    is_active: bool

class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int
    limit: int
    offset: int

class MemberUpdate(BaseModel):
    role: Role | None = None
    team_id: int | None = None

class InviteCreate(BaseModel):
    email: EmailStr
    role: Role
    team_id: int | None = None

class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    team_id: int | None
    expires_at: datetime

class InviteAccept(BaseModel):
    token: str
    # Required only when the invitee doesn't have an account yet.
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=128)

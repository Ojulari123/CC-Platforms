from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "manager", "engineer"]

class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

class DepartmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    # The one named person who runs the department. Distinct from the set of
    # people holding role="admin", and from platform admins (whole workspace).
    head_user_id: int | None = None
    head_name: str | None = None

class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

class TeamUpdate(BaseModel):
    """Rename only — the lead is appointed via .../teams/{id}/manager/{user_id}."""
    name: str = Field(min_length=1, max_length=200)

class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dept_id: int
    name: str
    slug: str
    manager_user_id: int | None = None
    manager_name: str | None = None

class TeamListItem(BaseModel):
    """A team seen outside its department's URL, so it carries the department
    with it — a bare list of team names across the company is ambiguous."""
    id: int
    name: str
    slug: str
    dept_id: int
    dept_name: str
    member_count: int
    manager_user_id: int | None = None
    manager_name: str | None = None

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

class InvitePreview(BaseModel):
    """What the accept page shows before asking for a password. Deliberately
    thin — this is public, so it leaks nothing beyond what the invitee was
    already told in their email."""
    email: EmailStr
    dept_name: str
    team_name: str | None = None
    role: str
    needs_account: bool  # False when the invitee already has an account

class InviteAccept(BaseModel):
    token: str
    # Required only when the invitee doesn't have an account yet.
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=128)

class PlatformAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    is_platform_admin: bool

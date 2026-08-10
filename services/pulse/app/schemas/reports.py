from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.users import UserRef

ReportStatus = Literal["draft", "submitted", "changes_requested", "approved", "rejected"]

class ReportCreate(BaseModel):
    repo_id: int
    week_start: date | None = None
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class GenerateRequest(BaseModel):
    repo_id: int
    week_start: date | None = None

class ReportUpdate(BaseModel):
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_user_id: int
    author: UserRef | None = None
    repo_id: int
    dept_id: int | None
    week_start: date
    status: str
    summary_manager: str | None
    summary_exec: str | None
    next_week_goals: str | None
    generated_at: datetime | None
    prompt_version: str | None
    created_at: datetime
    updated_at: datetime

class DecisionRequest(BaseModel):
    note: str | None = None

class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    actor_user_id: int
    actor: UserRef | None = None
    action: str
    note: str | None
    created_at: datetime

class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    author_user_id: int
    author: UserRef | None = None
    body: str
    created_at: datetime
    edited_at: datetime | None

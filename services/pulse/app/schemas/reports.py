from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

# The five report states. Used to validate the ?status= list filter, so a typo
# gets a clear 422 instead of silently matching nothing.
ReportStatus = Literal["draft", "submitted", "changes_requested", "approved", "rejected"]

class ReportCreate(BaseModel):
    """An engineer opens their weekly report for one repo. The report's department
    is taken from the repo; week_start defaults to the current week's Monday. One
    report per (engineer, repo, week)."""
    repo_id: int
    week_start: date | None = None
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class ReportUpdate(BaseModel):
    """Edit the draft. Author-only, and only while the report is still a draft or
    has been sent back for changes."""
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_user_id: int
    repo_id: int
    dept_id: int | None
    week_start: date
    status: str
    summary_manager: str | None
    summary_exec: str | None
    next_week_goals: str | None
    created_at: datetime
    updated_at: datetime

class DecisionRequest(BaseModel):
    """A lead's note when approving, rejecting, or asking for changes. Optional on
    approve; worth requiring in the UI for reject/changes, but not enforced here."""
    note: str | None = None

class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    actor_user_id: int
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
    body: str
    created_at: datetime
    edited_at: datetime | None

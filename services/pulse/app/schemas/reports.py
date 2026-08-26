from datetime import date, datetime, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.users import UserRef
from app.services.repo_index import is_valid_full_name

ReportStatus = Literal["draft", "submitted", "changes_requested", "approved", "rejected"]

# Six months. Long enough for a promotion case or a probation period, short enough that
# one request can't ask GitHub for a repository's entire history.
MAX_ADHOC_RANGE_DAYS = 180
MAX_ADHOC_SUBJECTS = 10

class ReportCreate(BaseModel):
    repo_id: int
    week_start: date | None = None
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class GenerateRequest(BaseModel):
    repo_id: int
    week_start: date | None = None
    persona_id: int | None = None

class AdhocSubject(BaseModel):
    """A contributor to report on: a Pulse user, or a bare GitHub login for someone who
    has no Pulse account — an outside collaborator still shows up in the repository."""

    user_id: int | None = None
    github_login: str | None = None

    @model_validator(mode="after")
    def _needs_an_identity(self) -> "AdhocSubject":
        if self.user_id is None and not (self.github_login or "").strip():
            raise ValueError("Each subject needs a user_id or a github_login")
        return self

class AdhocRequest(BaseModel):
    repo_id: int | None = None
    repo_full_name: str | None = None
    subjects: list[AdhocSubject] = Field(min_length=1, max_length=MAX_ADHOC_SUBJECTS)
    range_start: date
    range_end: date
    persona_id: int | None = None

    @model_validator(mode="after")
    def _one_repository_and_a_sane_range(self) -> "AdhocRequest":
        full_name = (self.repo_full_name or "").strip()
        if (self.repo_id is None) == (not full_name):
            raise ValueError("Give either repo_id (a repository Pulse tracks) or repo_full_name (owner/name), not both")
        # Checked here rather than in the service: this string is interpolated into a
        # GitHub URL, so it is refused before it can reach one.
        if full_name and not is_valid_full_name(full_name):
            raise ValueError("repo_full_name must be owner/name, for example cyphercrescent/pulse")
        self.repo_full_name = full_name or None
        if self.range_end < self.range_start:
            raise ValueError("range_end cannot be before range_start")
        if self.range_end - self.range_start > timedelta(days=MAX_ADHOC_RANGE_DAYS):
            raise ValueError(f"A report can cover at most {MAX_ADHOC_RANGE_DAYS} days")
        return self

class ReportUpdate(BaseModel):
    summary_manager: str | None = None
    summary_exec: str | None = None
    next_week_goals: str | None = None

class ReportSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    subject_user_id: int | None
    subject: UserRef | None = None
    subject_github_login: str | None
    section: str | None
    position: int
    created_at: datetime

class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_user_id: int
    author: UserRef | None = None
    subject_user_id: int | None = None
    subject: UserRef | None = None
    subject_github_login: str | None = None
    repo_id: int | None
    repo_full_name: str | None = None
    dept_id: int | None
    kind: str
    week_start: date | None
    range_start: date | None = None
    range_end: date | None = None
    subjects: list[ReportSubjectResponse] = []
    status: str
    summary_manager: str | None
    summary_exec: str | None
    next_week_goals: str | None
    generated_at: datetime | None
    prompt_version: str | None
    persona_id: int | None = None
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

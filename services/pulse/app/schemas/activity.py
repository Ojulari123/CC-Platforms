from datetime import date, datetime
from pydantic import BaseModel, ConfigDict
from app.schemas.users import UserRef

class ActivityCounts(BaseModel):
    commits: int
    pull_requests: int
    reviews: int
    issues: int

class CommitItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    repo_id: int
    sha: str
    message: str | None
    url: str | None
    committed_at: datetime

class PullRequestItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    repo_id: int
    number: int
    title: str | None
    state: str
    merged: bool
    url: str | None
    gh_created_at: datetime | None

class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pull_request_id: int
    state: str
    submitted_at: datetime | None
    url: str | None

class IssueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    repo_id: int
    number: int
    title: str | None
    state: str
    url: str | None
    gh_created_at: datetime | None

class ActivityResponse(BaseModel):
    """One engineer's synced GitHub activity: totals plus the most recent items of
    each kind. This is what the dashboard renders and what the AI summaries read."""
    user_id: int
    user: UserRef | None = None  # filled from identity; null if it can't be resolved
    since: date | None
    counts: ActivityCounts
    recent_commits: list[CommitItem]
    recent_pull_requests: list[PullRequestItem]
    recent_reviews: list[ReviewItem]
    recent_issues: list[IssueItem]

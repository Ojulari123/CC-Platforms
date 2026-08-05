"""The engineer activity view — reads the synced GitHub data (commits, PRs,
reviews, issues) for one person and rolls it up into counts + recent items.

All from Pulse's own tables, attributed by `author_user_id` / `reviewer_user_id`
"""
from datetime import date, datetime, time, timezone
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import Commit, Issue, PullRequest, Repository, Review
from app.schemas.activity import (
    ActivityCounts, ActivityResponse, CommitItem, IssueItem, PullRequestItem, ReviewItem,
)

_RECENT = 10  # how many of each kind to include as "recent"

def can_view(db: Session, user: TokenClaims, target_user_id: int) -> bool:
    """You can always see your own activity. Others' activity is visible to a
    platform admin, any department admin, or anyone who leads/deputises a repo
    (the people who review reports and need to see contributions)."""
    if target_user_id == user.user_id:
        return True
    if user.is_platform_admin:
        return True
    if any(m.role == "admin" for m in user.memberships):
        return True
    leads = db.scalar(
        select(func.count()).select_from(Repository).where(
            or_(Repository.lead_user_id == user.user_id, Repository.deputy_user_id == user.user_id)
        )
    )
    return bool(leads)

def _since_dt(since: date | None) -> datetime | None:
    return datetime.combine(since, time.min, tzinfo=timezone.utc) if since else None

def get_activity_response(db: Session, user_id: int, since: date | None = None, repo_id: int | None = None) -> ActivityResponse:
    s = _since_dt(since)

    cq = select(Commit).where(Commit.author_user_id == user_id)
    if s is not None:
        cq = cq.where(Commit.committed_at >= s)
    if repo_id is not None:
        cq = cq.where(Commit.repo_id == repo_id)
    commits = list(db.scalars(cq.order_by(Commit.committed_at.desc(), Commit.id.desc())))

    pq = select(PullRequest).where(PullRequest.author_user_id == user_id)
    if s is not None:
        pq = pq.where(PullRequest.gh_created_at >= s)
    if repo_id is not None:
        pq = pq.where(PullRequest.repo_id == repo_id)
    prs = list(db.scalars(pq.order_by(PullRequest.gh_created_at.desc(), PullRequest.id.desc())))

    rq = select(Review).where(Review.reviewer_user_id == user_id)
    if s is not None:
        rq = rq.where(Review.submitted_at >= s)
    if repo_id is not None:
        rq = rq.join(PullRequest, PullRequest.id == Review.pull_request_id).where(PullRequest.repo_id == repo_id)
    reviews = list(db.scalars(rq.order_by(Review.submitted_at.desc(), Review.id.desc())))

    iq = select(Issue).where(Issue.author_user_id == user_id)
    if s is not None:
        iq = iq.where(Issue.gh_created_at >= s)
    if repo_id is not None:
        iq = iq.where(Issue.repo_id == repo_id)
    issues = list(db.scalars(iq.order_by(Issue.gh_created_at.desc(), Issue.id.desc())))

    return ActivityResponse(
        user_id=user_id,
        since=since,
        counts=ActivityCounts(commits=len(commits), pull_requests=len(prs), reviews=len(reviews), issues=len(issues)),
        recent_commits=[CommitItem.model_validate(c) for c in commits[:_RECENT]],
        recent_pull_requests=[PullRequestItem.model_validate(p) for p in prs[:_RECENT]],
        recent_reviews=[ReviewItem.model_validate(r) for r in reviews[:_RECENT]],
        recent_issues=[IssueItem.model_validate(i) for i in issues[:_RECENT]],
    )

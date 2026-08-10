"""The engineer activity view — reads the synced GitHub data (commits, PRs,
reviews, issues) for one person and rolls it up into counts + recent items.

All from Pulse's own tables, attributed by `author_user_id` / `reviewer_user_id`
"""
from datetime import date, datetime, time, timezone
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import Commit, Issue, PullRequest, Repository, Review
from app.schemas.activity import (
    ActivityCounts, ActivityResponse, CommitItem, IssueItem, PullRequestItem, ReviewItem,
)

_RECENT = 10  # how many of each kind to include as "recent"

def _oversight_repo_ids(db: Session, user: TokenClaims) -> list[int]:
    """The repos the caller has any standing over: the ones they lead or deputise,
    plus every repo filed under a department they admin. Same vocabulary as the
    reports service's _can_approve / review_queue."""
    scope = [or_(Repository.lead_user_id == user.user_id, Repository.deputy_user_id == user.user_id)]
    admin_dept_ids = [m.dept_id for m in user.memberships if m.role == "admin"]
    if admin_dept_ids:
        scope.append(Repository.dept_id.in_(admin_dept_ids))
    return list(db.scalars(select(Repository.id).where(or_(*scope))))

def repo_ids_worked_in_q(user_id: int):
    """The repo ids this person shows up in — as a committer, PR/issue author, or
    reviewer. Pulse has no membership table, so worked-in is what it has.

    Returned as an unexecuted query so callers that filter repos in SQL (the
    repositories service) can drop it straight into an `IN (...)` instead of pulling
    the ids into Python. This is the single definition of "worked in"; don't write a
    second one."""
    return select(Commit.repo_id).where(Commit.author_user_id == user_id).union(
        select(PullRequest.repo_id).where(PullRequest.author_user_id == user_id),
        select(Issue.repo_id).where(Issue.author_user_id == user_id),
        select(PullRequest.repo_id).join(Review, Review.pull_request_id == PullRequest.id).where(Review.reviewer_user_id == user_id),
    )

def repo_ids_worked_in(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(repo_ids_worked_in_q(user_id)))

def visible_repo_ids(db: Session, user: TokenClaims, target_user_id: int) -> list[int] | None:
    """Which repos the caller may see this person's activity through.

    `None` means no restriction — you're looking at yourself, or you're a platform
    admin. Otherwise it's the overlap between the repos the caller oversees and the
    repos the target has actually worked in; an empty list means no overlap, so the
    caller has no business seeing this person at all.

    Pulse deliberately does not know which department a user belongs to — identity
    owns that and Pulse must not read identity's database. So a department admin's
    reach over a *person* is derived from the only departmental fact Pulse holds:
    which department a repo is filed under. In practice that reads as "you can see
    what this engineer did in your department's repos", which is the tightest rule
    the available data supports."""
    if target_user_id == user.user_id or user.is_platform_admin:
        return None
    worked_in = repo_ids_worked_in(db, target_user_id)
    return [rid for rid in _oversight_repo_ids(db, user) if rid in worked_in]

def _since_dt(since: date | None) -> datetime | None:
    return datetime.combine(since, time.min, tzinfo=timezone.utc) if since else None

def get_activity_response(db: Session, user_id: int, since: date | None = None, repo_id: int | None = None, repo_ids: list[int] | None = None) -> ActivityResponse:
    """`repo_id` is the caller's own filter; `repo_ids` is the permission scope from
    visible_repo_ids (None = unrestricted). Both narrow, so a scoped viewer never
    sees counts from repos they have no standing over."""
    s = _since_dt(since)

    def _repo_clause(column):
        clauses = []
        if repo_id is not None:
            clauses.append(column == repo_id)
        if repo_ids is not None:
            clauses.append(column.in_(repo_ids))
        return clauses

    cq = select(Commit).where(Commit.author_user_id == user_id, *_repo_clause(Commit.repo_id))
    if s is not None:
        cq = cq.where(Commit.committed_at >= s)
    commits = list(db.scalars(cq.order_by(Commit.committed_at.desc(), Commit.id.desc())))

    pq = select(PullRequest).where(PullRequest.author_user_id == user_id, *_repo_clause(PullRequest.repo_id))
    if s is not None:
        pq = pq.where(PullRequest.gh_created_at >= s)
    prs = list(db.scalars(pq.order_by(PullRequest.gh_created_at.desc(), PullRequest.id.desc())))

    rq = select(Review).where(Review.reviewer_user_id == user_id)
    if s is not None:
        rq = rq.where(Review.submitted_at >= s)
    if repo_id is not None or repo_ids is not None:
        rq = rq.join(PullRequest, PullRequest.id == Review.pull_request_id).where(*_repo_clause(PullRequest.repo_id))
    reviews = list(db.scalars(rq.order_by(Review.submitted_at.desc(), Review.id.desc())))

    iq = select(Issue).where(Issue.author_user_id == user_id, *_repo_clause(Issue.repo_id))
    if s is not None:
        iq = iq.where(Issue.gh_created_at >= s)
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

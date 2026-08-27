from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.config import settings
from app.models import Commit, Issue, PullRequest, Repository, Review
from app.schemas.activity import (
    ActivityCounts, ActivityResponse, CommitItem, IssueItem, PullRequestItem, ReviewItem,
)

_RECENT = 10

def _oversight_repo_ids(db: Session, user: TokenClaims) -> list[int]:
    scope = [or_(Repository.lead_user_id == user.user_id, Repository.deputy_user_id == user.user_id)]
    admin_dept_ids = [m.dept_id for m in user.memberships if m.role == "admin"]
    if admin_dept_ids:
        scope.append(Repository.dept_id.in_(admin_dept_ids))
    return list(db.scalars(select(Repository.id).where(or_(*scope))))

def visibility_activity_cutoff() -> datetime:
    """How far back activity still counts as evidence of access.

    Being lead, deputy or a member of the repo's department is *current* state: it comes
    off an access token minted minutes ago and stops being true the moment an admin
    changes it. Having authored a commit is not — it is evidence that someone had access
    once, and left unbounded it grants read on an old team's repositories forever. So the
    activity grant decays: work older than REPO_VISIBILITY_ACTIVITY_DAYS no longer opens
    a repository on its own.

    The window is the staleness we accept. Someone who moves department loses the
    department grant the same day and the activity grant at most that many days later,
    because after the move they stop committing there. It is not shorter because an
    engineer legitimately reads and finishes reports covering work done before the move.
    """
    return datetime.now(timezone.utc) - timedelta(days=settings.REPO_VISIBILITY_ACTIVITY_DAYS)


def repo_ids_worked_in_q(user_id: int, since: datetime | None = None):
    """Returned unexecuted so callers that filter repos in SQL can drop it into an
    `IN (...)`. This is the single definition of "worked in"; don't write a second one.

    `since` drops activity older than that instant. Each of the four sources is dated by
    the column the rest of this module already orders it by, so "worked in recently" and
    "recent activity" mean the same thing. Rows with a null timestamp are dropped by the
    comparison, which is the safe direction for the caller that uses this to decide who
    may read a repository."""
    def _window(q, column):
        return q if since is None else q.where(column >= since)

    return _window(select(Commit.repo_id).where(Commit.author_user_id == user_id), Commit.committed_at).union(
        _window(select(PullRequest.repo_id).where(PullRequest.author_user_id == user_id), PullRequest.gh_created_at),
        _window(select(Issue.repo_id).where(Issue.author_user_id == user_id), Issue.gh_created_at),
        _window(select(PullRequest.repo_id).join(Review, Review.pull_request_id == PullRequest.id).where(Review.reviewer_user_id == user_id), Review.submitted_at),
    )

def repo_ids_worked_in(db: Session, user_id: int, since: datetime | None = None) -> set[int]:
    return set(db.scalars(repo_ids_worked_in_q(user_id, since)))

def user_ids_worked_in_repo(db: Session, repo_id: int) -> set[int]:
    """The mirror of repo_ids_worked_in_q — who worked in one repo, rather than which
    repos one person worked in. Same four activity sources, so keep the two in step.
    Sync leaves author/reviewer null for a GitHub login it couldn't match to an identity
    user, and those nulls are dropped: they are not people we can name."""
    q = select(Commit.author_user_id).where(Commit.repo_id == repo_id).union(
        select(PullRequest.author_user_id).where(PullRequest.repo_id == repo_id),
        select(Issue.author_user_id).where(Issue.repo_id == repo_id),
        select(Review.reviewer_user_id).join(PullRequest, PullRequest.id == Review.pull_request_id).where(PullRequest.repo_id == repo_id),
    )
    return {uid for uid in db.scalars(q) if uid is not None}

def visible_repo_ids(db: Session, user: TokenClaims, target_user_id: int) -> list[int] | None:
    """`None` means no restriction, not "nothing found" — an empty list is no overlap.

    Pulse must not read identity's database, so it doesn't know a user's department: a
    department admin's reach over a *person* is derived from the only departmental fact
    Pulse holds, which department a repo is filed under.

    The target's side of the overlap uses the same activity window as repo visibility, so
    "which of my repos did this person work in" ages out exactly when their own read
    access to those repos does."""
    if target_user_id == user.user_id or user.is_platform_admin:
        return None
    worked_in = repo_ids_worked_in(db, target_user_id, visibility_activity_cutoff())
    return [rid for rid in _oversight_repo_ids(db, user) if rid in worked_in]

def _since_dt(since: date | None) -> datetime | None:
    return datetime.combine(since, time.min, tzinfo=timezone.utc) if since else None

def get_activity_response(db: Session, user_id: int, since: date | None = None, repo_id: int | None = None, repo_ids: list[int] | None = None) -> ActivityResponse:
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

import logging
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import STATUS_DRAFT, Commit, Issue, LlmUsage, PullRequest, Report, Repository, Review
from app.services import llm
from app.services.prompts import PROMPT_VERSION
from app.services.reports import _EDITABLE, _may_report_on, _monday

logger = logging.getLogger(__name__)

# Counts stay exact; only the item lists sent to the prompt are capped, and the payload
# is flagged when that happens.
_MAX_ITEMS_PER_KIND = 50

class NoActivityError(Exception):
    pass

class ReportConflictError(Exception):
    pass

def _week_window(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)

def _commit_item(c: Commit) -> dict:
    return {"sha": c.sha, "message": c.message, "committed_at": c.committed_at}

def _pr_item(p: PullRequest) -> dict:
    return {"number": p.number, "title": p.title, "state": p.state, "merged": p.merged, "gh_created_at": p.gh_created_at}

def _review_item(r: Review) -> dict:
    return {"pull_request_id": r.pull_request_id, "state": r.state, "submitted_at": r.submitted_at}

def _issue_item(i: Issue) -> dict:
    return {"number": i.number, "title": i.title, "state": i.state, "gh_created_at": i.gh_created_at}

def _collect_week_activity(db: Session, user_id: int, repo_id: int, week_start: date) -> dict:
    lo, hi = _week_window(week_start)

    cq = select(Commit).where(
        Commit.author_user_id == user_id, Commit.repo_id == repo_id,
        Commit.committed_at >= lo, Commit.committed_at < hi,
    )
    commits = list(db.scalars(cq.order_by(Commit.committed_at.desc(), Commit.id.desc())))

    pq = select(PullRequest).where(
        PullRequest.author_user_id == user_id, PullRequest.repo_id == repo_id,
        PullRequest.gh_created_at >= lo, PullRequest.gh_created_at < hi,
    )
    prs = list(db.scalars(pq.order_by(PullRequest.gh_created_at.desc(), PullRequest.id.desc())))

    rq = (
        select(Review)
        .join(PullRequest, PullRequest.id == Review.pull_request_id)
        .where(
            Review.reviewer_user_id == user_id, PullRequest.repo_id == repo_id,
            Review.submitted_at >= lo, Review.submitted_at < hi,
        )
    )
    reviews = list(db.scalars(rq.order_by(Review.submitted_at.desc(), Review.id.desc())))

    iq = select(Issue).where(
        Issue.author_user_id == user_id, Issue.repo_id == repo_id,
        Issue.gh_created_at >= lo, Issue.gh_created_at < hi,
    )
    issues = list(db.scalars(iq.order_by(Issue.gh_created_at.desc(), Issue.id.desc())))

    n = _MAX_ITEMS_PER_KIND
    truncated = any(len(x) > n for x in (commits, prs, reviews, issues))
    return {
        "week_start": week_start,
        "counts": {
            "commits": len(commits), "pull_requests": len(prs),
            "reviews": len(reviews), "issues": len(issues),
        },
        "truncated": truncated,
        "commits": [_commit_item(c) for c in commits[:n]],
        "pull_requests": [_pr_item(p) for p in prs[:n]],
        "reviews": [_review_item(r) for r in reviews[:n]],
        "issues": [_issue_item(i) for i in issues[:n]],
    }

def _total_items(activity: dict) -> int:
    c = activity["counts"]
    return c["commits"] + c["pull_requests"] + c["reviews"] + c["issues"]

def generate_report(db: Session, user: TokenClaims, repo_id: int, week_start: date | None = None) -> Report:
    repo = db.get(Repository, repo_id)
    if not repo:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Repository not found")
    if not _may_report_on(db, user, repo):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail=(
                "You have no synced activity in this repo. Reports are for repos "
                "you've worked in. If your GitHub isn't connected or synced yet, "
                "do that first."
            ),
        )

    week = _monday(week_start or date.today())

    existing = db.scalar(
        select(Report).where(
            Report.author_user_id == user.user_id,
            Report.repo_id == repo.id,
            Report.week_start == week,
        )
    )
    if existing is not None and existing.status not in _EDITABLE:
        raise ReportConflictError(
            f"A {existing.status} report already exists for this repo for the week of "
            f"{week.isoformat()} and can't be regenerated."
        )

    activity = _collect_week_activity(db, user.user_id, repo.id, week)
    if _total_items(activity) == 0:
        raise NoActivityError(
            f"No synced GitHub activity for the week of {week.isoformat()} in this repo, "
            "so there is nothing to generate a report from."
        )

    result = llm.generate_summaries(activity)
    logger.info(
        "generate_report: user=%s repo=%s week=%s model=%s tokens=%s truncated=%s",
        user.user_id, repo.id, week.isoformat(), result.model, result.token_count, activity["truncated"],
    )

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.summary_manager = result.summary_manager
        existing.summary_exec = result.summary_exec
        existing.next_week_goals = result.next_week_goals
        existing.generated_at = now
        existing.prompt_version = PROMPT_VERSION
        report = existing
    else:
        report = Report(
            author_user_id=user.user_id,
            repo_id=repo.id,
            dept_id=repo.dept_id,
            week_start=week,
            status=STATUS_DRAFT,
            summary_manager=result.summary_manager,
            summary_exec=result.summary_exec,
            next_week_goals=result.next_week_goals,
            generated_at=now,
            prompt_version=PROMPT_VERSION,
        )
        db.add(report)

    # The usage row goes in the SAME transaction as the report: a second commit meant a
    # failed ledger write 500'd a report that was already saved, so the caller retried
    # and paid for another generation.
    db.flush()
    db.add(LlmUsage(report_id=report.id, user_id=user.user_id, tokens=result.token_count or 0))
    db.commit()
    db.refresh(report)
    return report

import logging
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import select
from app.config import settings
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import LLM_KIND_REPORT, PROVIDER_OPENAI, REPORT_KIND_WEEKLY, STATUS_DRAFT, Commit, Issue, LlmUsage, PullRequest, Report, Repository, RepoJournal, Review
from app.services import credentials, llm, llm_budget, persona_prompts, personas, prompts
from app.services.prompts import PROMPT_VERSION
from app.services.repositories import may_write_on_repo
from app.services.sync import collapse_commits, collapse_note
from app.services.reports import _EDITABLE, _monday

logger = logging.getLogger(__name__)

# Counts stay exact; only the item lists sent to the prompt are capped, and the payload
# is flagged when that happens.
_MAX_ITEMS_PER_KIND = 50

# The two sources next week's goals are drawn from. Journal entries are prose and cost
# far more per item than a commit subject, so they are capped harder. A body longer than
# this is cut rather than dropped: the opening of an entry is where somebody says what
# they are doing, and the alternative is losing the entry entirely.
_MAX_STATED_ITEMS = 15
_MAX_JOURNAL_CHARS = 1500

class NoActivityError(Exception):
    pass

class ReportConflictError(Exception):
    pass

def _week_window(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)

def _commit_item(c: Commit) -> dict:
    return {"sha": c.sha, "message": c.message, "committed_at": c.committed_at}

# Closure dates are sent, and sent as an explicit null when absent, so the model never has
# to work out what `state: "closed"` means from the one date it holds. A pull request the
# sync last saw before it stored closed_at reads null until GitHub lists it as updated again.
def _pr_item(p: PullRequest) -> dict:
    return {"number": p.number, "title": p.title, "state": p.state, "merged": p.merged, "gh_created_at": p.gh_created_at, "merged_at": p.merged_at, "closed_at": p.closed_at}

def _review_item(r: Review, pr_number: int) -> dict:
    # The pull request's GitHub number, not its row id: a row id printed as "#12" reads as
    # a pull request number and is almost never the same one.
    return {"pull_request_number": pr_number, "state": r.state, "submitted_at": r.submitted_at}

def _issue_item(i: Issue) -> dict:
    return {"number": i.number, "title": i.title, "state": i.state, "gh_created_at": i.gh_created_at, "closed_at": i.closed_at}

# Stated intent, which is a different thing from activity and is kept apart from it in
# the payload. An open issue assigned to somebody is work queued to them; a due date on
# its milestone is a date another person set, not one this report worked out.
def _assigned_issue_item(i: Issue) -> dict:
    return {
        "number": i.number, "title": i.title, "url": i.url,
        "milestone": i.milestone_title, "due_on": i.milestone_due_on,
    }

def _journal_item(j: RepoJournal) -> dict:
    body = j.body or ""
    return {
        "written_at": j.created_at,
        "body": body[:_MAX_JOURNAL_CHARS],
        "truncated": len(body) > _MAX_JOURNAL_CHARS,
    }

def _stated_intent(db: Session, user_id: int, repo_id: int, lo: datetime, hi: datetime) -> dict:
    """What the person said they would do, as opposed to what the week shows they did.

    Two sources, both already in the database. Journal entries are scoped to the report's
    own week so a report reads the same way whenever it is regenerated; open issues are
    not, because an issue assigned in March and still open is still queued work. Neither
    is filtered by whether it looks like a plan: that judgement belongs to whoever reads
    the report, and inventing the judgement here is the defect this replaces.
    """
    jq = select(RepoJournal).where(
        RepoJournal.author_user_id == user_id, RepoJournal.repo_id == repo_id,
        RepoJournal.created_at >= lo, RepoJournal.created_at < hi,
    )
    journals = list(db.scalars(jq.order_by(RepoJournal.created_at.desc(), RepoJournal.id.desc())))
    aq = select(Issue).where(
        Issue.assignee_user_id == user_id, Issue.repo_id == repo_id, Issue.state == "open",
    )
    assigned = list(db.scalars(aq.order_by(Issue.milestone_due_on.asc().nullslast(), Issue.gh_created_at.desc(), Issue.id.desc())))
    n = _MAX_STATED_ITEMS
    return {
        "counts": {"journal_entries": len(journals), "assigned_open_issues": len(assigned)},
        "truncated": len(journals) > n or len(assigned) > n,
        # Oldest first: entries read as a week in the order it happened.
        "journal_entries": [_journal_item(j) for j in reversed(journals[:n])],
        "assigned_open_issues": [_assigned_issue_item(i) for i in assigned[:n]],
    }

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
        select(Review, PullRequest.number)
        .join(PullRequest, PullRequest.id == Review.pull_request_id)
        .where(
            Review.reviewer_user_id == user_id, PullRequest.repo_id == repo_id,
            Review.submitted_at >= lo, Review.submitted_at < hi,
        )
    )
    reviews = list(db.execute(rq.order_by(Review.submitted_at.desc(), Review.id.desc())).all())

    iq = select(Issue).where(
        Issue.author_user_id == user_id, Issue.repo_id == repo_id,
        Issue.gh_created_at >= lo, Issue.gh_created_at < hi,
    )
    issues = list(db.scalars(iq.order_by(Issue.gh_created_at.desc(), Issue.id.desc())))

    # Newest first, which is what collapse_commits needs. See sync.collapse_commits for
    # why a merge commit and a squashed duplicate are not two changes.
    commit_items, merges, duplicates = collapse_commits([_commit_item(c) for c in commits])
    note = collapse_note(merges, duplicates)

    n = _MAX_ITEMS_PER_KIND
    truncated = any(len(x) > n for x in (commit_items, prs, reviews, issues))
    return {
        "week_start": week_start,
        # Inclusive, and stated rather than left to be worked out from "week".
        "week_end": week_start + timedelta(days=6),
        "counts": {
            "commits": len(commit_items), "pull_requests": len(prs),
            "reviews": len(reviews), "issues": len(issues),
        },
        "truncated": truncated,
        "notes": [note] if note else [],
        "commits": commit_items[:n],
        "pull_requests": [_pr_item(p) for p in prs[:n]],
        "reviews": [_review_item(r, number) for r, number in reviews[:n]],
        "issues": [_issue_item(i) for i in issues[:n]],
        # Kept in its own block, and named for what it is. Everything above is a record of
        # what happened; this is the only part of the payload anybody stated on purpose,
        # and next week's goals may be written from nothing else.
        "stated_intent": _stated_intent(db, user_id, repo_id, lo, hi),
    }

def _total_items(activity: dict) -> int:
    c = activity["counts"]
    return c["commits"] + c["pull_requests"] + c["reviews"] + c["issues"]

def generate_report(db: Session, user: TokenClaims, repo_id: int, week_start: date | None = None, persona_id: int | None = None) -> Report:
    repo = db.get(Repository, repo_id)
    if not repo:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Repository not found")
    if not may_write_on_repo(db, user, repo):
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

    persona = personas.resolve(db, user, persona_id)
    # Pinned to OpenAI: this path speaks the JSON-schema API in llm.py, so an Anthropic
    # key at any scope is not a candidate and the resolution skips straight past it.
    credential = credentials.resolve_credential(db, user, provider=PROVIDER_OPENAI)
    # Both halves of what this call can cost: the prompt, which is known exactly, and the
    # reply, which is not, but max_tokens is the most it can be. Checked before the call
    # rather than after, so the cap refuses spending instead of reporting it.
    system_prompt = persona_prompts.apply_to_system_prompt(prompts.build_system_prompt(), persona)
    user_prompt = prompts.build_user_prompt(activity)
    llm_budget.check_budget(
        db, user.user_id, kind=LLM_KIND_REPORT, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin,
        estimated_tokens=llm_budget.estimate_tokens([system_prompt, user_prompt]) + settings.AI_MAX_OUTPUT_TOKENS,
    )
    result = llm.generate_summaries(
        activity,
        system_prompt=system_prompt,
        credential=credential,
    )
    logger.info(
        "generate_report: user=%s repo=%s week=%s persona=%s key=%s model=%s tokens=%s truncated=%s",
        user.user_id, repo.id, week.isoformat(), persona.id,
        credential.source if credential else "none", result.model, result.token_count, activity["truncated"],
    )

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.summary_manager = result.summary_manager
        existing.summary_exec = result.summary_exec
        existing.next_week_goals = result.next_week_goals
        existing.generated_at = now
        existing.prompt_version = PROMPT_VERSION
        existing.persona_id = persona.id
        report = existing
    else:
        report = Report(
            author_user_id=user.user_id,
            subject_user_id=user.user_id,
            repo_id=repo.id,
            repo_full_name=repo.full_name,
            dept_id=repo.dept_id,
            kind=REPORT_KIND_WEEKLY,
            week_start=week,
            range_start=week,
            range_end=week + timedelta(days=6),
            status=STATUS_DRAFT,
            summary_manager=result.summary_manager,
            summary_exec=result.summary_exec,
            next_week_goals=result.next_week_goals,
            generated_at=now,
            prompt_version=PROMPT_VERSION,
            persona_id=persona.id,
        )
        db.add(report)

    # The usage row goes in the SAME transaction as the report: a second commit meant a
    # failed ledger write 500'd a report that was already saved, so the caller retried
    # and paid for another generation.
    db.flush()
    db.add(LlmUsage(report_id=report.id, kind=LLM_KIND_REPORT, user_id=user.user_id, tokens=result.token_count or 0))
    db.commit()
    db.refresh(report)
    return report

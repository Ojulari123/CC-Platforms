"""Ad-hoc reports: several named contributors, one repository, an arbitrary date range.

One service path with two data sources.

  * Mode A (synced) — `repo_id` names a repository Pulse tracks, and the activity is read
    out of the local tables. No GitHub call is made.
  * Mode B (live) — `repo_full_name` names any repository, tracked or not, and the
    activity is fetched from GitHub for the range.

The permission gate on Mode B is GitHub's own, not one Pulse invented. A public repository
is public, so any authenticated caller may report on it and no membership is checked. A
private one is readable only if the CALLER'S OWN stored OAuth token can read it: Pulse
makes the request with their token and treats GitHub's 404/403 as the answer. That is
deliberate — it means Pulse can never be used to read a repository the person asking
could not have opened themselves. A private Mode B request only works if the caller's
token carries the `repo` scope, so an account connected before GITHUB_OAUTH_SCOPES was
widened gets the reconnect message instead of a report.

Mode A keeps the existing visibility rule (repositories.get_repository, 404 not 403).

Each contributor gets their own section, generated from a payload containing only their
records. Two people's work therefore cannot be blended or swapped, because the model
writing one section has never been shown the other person's data.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app import crypto
from app.config import settings
from app.models import (
    LLM_KIND_REPORT, REPORT_KIND_ADHOC, STATUS_DRAFT,
    Commit, Issue, LlmUsage, PullRequest, Report, ReportSubject, Review,
)
from app.services import adhoc_prompts, ai_provider, credentials, github_oauth, llm_budget, personas, repositories as repo_service
from app.services.github_client import GitHubClient, GitHubRateLimited
from app.services.repo_index import RECONNECT_DETAIL
from app.services.sync import collapse_commits, collapse_note, commit_author_login, commit_stamp

logger = logging.getLogger(__name__)

# Same cap and the same reason as generation._MAX_ITEMS_PER_KIND: counts stay exact, only
# the item lists sent to the model are trimmed, and the payload says when they were.
_MAX_ITEMS_PER_KIND = 50

# Reviews are one GitHub request per pull request, so a live fetch only asks about the
# pull requests touched in the range, newest first, and stops here. Beyond it the report
# says reviews may be incomplete rather than spending an unbounded number of calls.
_MAX_LIVE_REVIEW_PRS = 30

NO_GITHUB_ACCESS_DETAIL = (
    "Pulse could not read {full_name} with your GitHub connection. If it is private, "
    "Pulse only reads it with your own token and never with a wider one. " + RECONNECT_DETAIL
)

# A caller with no stored token is a different problem with a different fix: there is
# nothing to reconnect. Pulse asks GitHub anonymously for them, and anonymous requests
# see no private repository and share GitHub's 60/hour pool with every other
# unauthenticated caller from this host — so "wait an hour" would be wrong advice.
NO_GITHUB_ACCOUNT_DETAIL = (
    "Pulse could not read {full_name} because your GitHub account is not connected. "
    "Connect it in Pulse and try again. Without a connection Pulse can only ask GitHub "
    "anonymously, which cannot see private repositories at all."
)

class AdhocRefused(Exception):
    """Something the caller can fix: an unknown contributor, a repository their GitHub
    connection can't read. The message is written for a person."""

    def __init__(self, message: str, status_code: int = 422):
        self.status_code = status_code
        super().__init__(message)

@dataclass
class Subject:
    user_id: int | None
    github_login: str | None
    activity: dict = field(default_factory=dict)
    section: str = ""

    @property
    def label(self) -> str:
        return self.github_login or f"user #{self.user_id}"

def _window(range_start: date, range_end: date) -> tuple[datetime, datetime]:
    """Half-open, and the end date is inclusive: someone asking for the 1st to the 7th
    means work done on the 7th counts."""
    lo = datetime.combine(range_start, time.min, tzinfo=timezone.utc)
    return lo, datetime.combine(range_end + timedelta(days=1), time.min, tzinfo=timezone.utc)

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def _pack(commits: list[dict], prs: list[dict], reviews: list[dict], issues: list[dict], notes: list[str]) -> dict:
    n = _MAX_ITEMS_PER_KIND
    truncated = any(len(x) > n for x in (commits, prs, reviews, issues))
    return {
        # pull_requests_merged is counted here rather than left to the model. Measured
        # against pallets/click, gpt-4o-mini given only per-item `merged` booleans
        # answered "three merged", "six merged" and "seven merged" across runs of the
        # same data — arithmetic is the one thing it should never be asked for in a
        # report with somebody's name on it.
        "counts": {
            "commits": len(commits), "pull_requests": len(prs),
            "pull_requests_merged": sum(1 for pr in prs if pr.get("merged")),
            "reviews": len(reviews), "issues": len(issues),
        },
        "truncated": truncated,
        "notes": list(notes),
        "commits": commits[:n],
        "pull_requests": prs[:n],
        "reviews": reviews[:n],
        "issues": issues[:n],
    }

def total_items(activity: dict) -> int:
    # merged pull requests are a subset of pull_requests, so counting them again would
    # make an empty-looking range look non-empty.
    counts = activity["counts"]
    return counts["commits"] + counts["pull_requests"] + counts["reviews"] + counts["issues"]

def _login_match(column, login: str):
    return func.lower(column) == login.lower()

def _synced_activity(db: Session, repo_id: int, subject: Subject, lo: datetime, hi: datetime) -> dict:
    """Mode A. A subject given as a user id matches on the id; one given as a bare login
    matches on the login the sync recorded, which is the only handle an external
    contributor has."""
    def author(model):
        if subject.user_id is not None:
            return model.author_user_id == subject.user_id
        return _login_match(model.author_github_login, subject.github_login)

    commits = list(db.scalars(
        select(Commit)
        .where(Commit.repo_id == repo_id, author(Commit), Commit.committed_at >= lo, Commit.committed_at < hi)
        .order_by(Commit.committed_at.desc(), Commit.id.desc())
    ))
    prs = list(db.scalars(
        select(PullRequest)
        .where(PullRequest.repo_id == repo_id, author(PullRequest), PullRequest.gh_created_at >= lo, PullRequest.gh_created_at < hi)
        .order_by(PullRequest.gh_created_at.desc(), PullRequest.id.desc())
    ))
    reviewer = Review.reviewer_user_id == subject.user_id if subject.user_id is not None else _login_match(Review.reviewer_github_login, subject.github_login)
    reviews = list(db.execute(
        select(Review, PullRequest.number)
        .join(PullRequest, PullRequest.id == Review.pull_request_id)
        .where(PullRequest.repo_id == repo_id, reviewer, Review.submitted_at >= lo, Review.submitted_at < hi)
        .order_by(Review.submitted_at.desc(), Review.id.desc())
    ).all())
    issues = list(db.scalars(
        select(Issue)
        .where(Issue.repo_id == repo_id, author(Issue), Issue.gh_created_at >= lo, Issue.gh_created_at < hi)
        .order_by(Issue.gh_created_at.desc(), Issue.id.desc())
    ))
    # Newest first, which is what collapse_commits needs: the squash on the default
    # branch is more recent than the branch commits it absorbed, so it is the one kept.
    commit_items, merges, duplicates = collapse_commits(
        [{"sha": c.sha, "message": c.message, "committed_at": c.committed_at} for c in commits]
    )
    note = collapse_note(merges, duplicates)
    # Every date a closed item could have is sent, and sent as an explicit null when it is
    # missing. A model given `state: "closed"` and one date treats that date as the closure
    # (a real report said issue #6093 "was closed on July 13" when July 13 was the day it
    # was opened). A pull request closed before the sync stored closed_at still reads null
    # until GitHub next lists it as updated.
    return _pack(
        commit_items,
        [{"number": p.number, "title": p.title, "state": p.state, "merged": p.merged, "created_at": p.gh_created_at, "merged_at": p.merged_at, "closed_at": p.closed_at} for p in prs],
        [{"pull_request_number": number, "state": r.state, "submitted_at": r.submitted_at} for r, number in reviews],
        [{"number": i.number, "title": i.title, "state": i.state, "created_at": i.gh_created_at, "closed_at": i.closed_at} for i in issues],
        [note] if note else [],
    )

def _fetch_live(client, full_name: str, lo: datetime, hi: datetime) -> dict:
    """Mode B, fetched once for the whole report and partitioned per contributor in
    Python. Per-subject fetching would multiply GitHub's rate limit by the number of
    people named."""
    since = lo.isoformat()
    # Filtered on the committer date, the same field the synced path stores and the same
    # one GitHub's `since` applies, so the range means one thing in both modes.
    commits = [c for c in client.list_commits(full_name, since=since) if lo <= (_parse_dt(commit_stamp(c)) or lo) < hi]
    # Everything updated since the range opened, in updated-desc order. Authored pull
    # requests are filtered out of it below, and reviews are read from the same list —
    # a review lands on a pull request opened long before the range.
    touched = client.list_pull_requests(full_name, since=lo)
    prs = [p for p in touched if lo <= (_parse_dt(p.get("created_at")) or hi) < hi]
    # GitHub's issues endpoint returns pull requests as issues; the `pull_request` key is
    # the only thing distinguishing them, and counting a PR twice would inflate the report.
    issues = [i for i in client.list_issues(full_name, since=since) if "pull_request" not in i and lo <= (_parse_dt(i.get("created_at")) or hi) < hi]

    capped = len(touched) > _MAX_LIVE_REVIEW_PRS
    reviews: list[dict] = []
    for pr in touched[:_MAX_LIVE_REVIEW_PRS]:
        for review in client.list_reviews(full_name, pr["number"]):
            submitted = _parse_dt(review.get("submitted_at"))
            if submitted is not None and lo <= submitted < hi:
                reviews.append({"login": ((review.get("user") or {}).get("login") or ""), "pull_request_number": pr["number"], "state": review.get("state"), "submitted_at": review.get("submitted_at")})
    return {"commits": commits, "pull_requests": prs, "issues": issues, "reviews": reviews, "review_prs_capped": capped}

def _live_activity(raw: dict, subject: Subject) -> dict:
    login = (subject.github_login or "").lower()

    def by(item) -> bool:
        return ((item.get("user") or {}).get("login") or "").lower() == login

    commits, merges, duplicates = collapse_commits([
        {"sha": c.get("sha"), "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0], "committed_at": commit_stamp(c)}
        for c in raw["commits"]
        if (commit_author_login(c) or "").lower() == login
    ])
    # See _synced_activity: closed and merged dates go to the model rather than being left
    # for it to infer from `state` and the one date it was given. GitHub's own null is
    # passed through, so an open item says so explicitly.
    prs = [
        {"number": p.get("number"), "title": p.get("title"), "state": p.get("state"), "merged": p.get("merged_at") is not None, "created_at": p.get("created_at"), "merged_at": p.get("merged_at"), "closed_at": p.get("closed_at")}
        for p in raw["pull_requests"] if by(p)
    ]
    issues = [
        {"number": i.get("number"), "title": i.get("title"), "state": i.get("state"), "created_at": i.get("created_at"), "closed_at": i.get("closed_at")}
        for i in raw["issues"] if by(i)
    ]
    reviews = [{k: v for k, v in r.items() if k != "login"} for r in raw["reviews"] if r["login"].lower() == login]
    notes = []
    note = collapse_note(merges, duplicates)
    if note:
        notes.append(note)
    if raw["review_prs_capped"]:
        notes.append(f"Reviews were only read from the {_MAX_LIVE_REVIEW_PRS} most recently updated pull requests, so this contributor may have reviewed more.")
    return _pack(commits, prs, reviews, issues, notes)

def _live_client(db: Session, user: TokenClaims, make_client=None) -> tuple[object, bool]:
    """The caller's own token or none at all. Pulse never reaches for a more privileged
    token than the person asking holds — a service token here would turn an ad-hoc report
    into a way to read repositories the caller cannot open.

    The flag says whether a token was found, because every GitHub refusal means something
    different without one.
    """
    account = github_oauth.get_account(db, user.user_id)
    token = crypto.decrypt(account.access_token_encrypted) if account else ""
    return (make_client or GitHubClient)(token), bool(token)

def _close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()

def _subject_payload(repo_name: str, range_start: date, range_end: date, subject: Subject) -> dict:
    return {
        "repository": repo_name,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "contributor": subject.label,
        **subject.activity,
    }

def _empty_section(subject: Subject, repo_name: str, range_start: date, range_end: date) -> str:
    """Written here rather than asked of the model: there is nothing to summarise, and a
    generated sentence about an absence is exactly where an unfounded judgement appears."""
    return (
        f"No commits, pull requests, reviews or issues are recorded for {subject.label} in "
        f"{repo_name} between {range_start.isoformat()} and {range_end.isoformat()}. This "
        "report only sees GitHub records, so that is not evidence that no work happened."
    )

def _resolve_subjects(db: Session, payload, *, live: bool) -> list[Subject]:
    subjects = [Subject(user_id=s.user_id, github_login=(s.github_login or "").strip() or None) for s in payload.subjects]
    if not live:
        return subjects
    for subject in subjects:
        if subject.github_login:
            continue
        account = github_oauth.get_account(db, subject.user_id)
        if account is None:
            raise AdhocRefused(
                f"Pulse doesn't know the GitHub login for user #{subject.user_id}, and a live "
                "report is matched on GitHub logins. Give that subject's github_login instead."
            )
        subject.github_login = account.github_login
    return subjects

def _compile(subjects: list[Subject]) -> str:
    return "\n\n".join(f"{s.label}\n{s.section}" for s in subjects)

def generate_adhoc_report(db: Session, user: TokenClaims, payload, make_client=None) -> Report:
    live = payload.repo_id is None
    repo = None
    if live:
        repo_name = payload.repo_full_name
    else:
        # 404, not 403, on a repo the caller can't see — repositories.get_repository's
        # convention, kept so an ad-hoc report can't be used to confirm a repo exists.
        repo = repo_service.get_repository(db, user, payload.repo_id)
        repo_name = repo.full_name

    subjects = _resolve_subjects(db, payload, live=live)
    lo, hi = _window(payload.range_start, payload.range_end)

    if live:
        client, authenticated = _live_client(db, user, make_client)
        no_access = (NO_GITHUB_ACCESS_DETAIL if authenticated else NO_GITHUB_ACCOUNT_DETAIL).format(full_name=repo_name)
        try:
            try:
                meta = client.get_repo(repo_name)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    # Deliberately the same answer for "private and you can't read it" and
                    # "no such repository": telling them apart is how an endpoint becomes a
                    # way to discover which private repositories exist.
                    raise AdhocRefused(no_access, status_code=403)
                raise
            raw = _fetch_live(client, repo_name, lo, hi)
        except GitHubRateLimited:
            # A connected caller genuinely ran out of their own 5,000/hour and the wait is
            # the honest answer. An anonymous one is sharing the 60/hour pool, and telling
            # them to wait sends them back to the same wall — connecting is the fix.
            if authenticated:
                raise
            raise AdhocRefused(no_access, status_code=403)
        finally:
            _close(client)
        logger.info("adhoc live fetch: user=%s repo=%s private=%s", user.user_id, repo_name, bool(meta.get("private")))
        for subject in subjects:
            subject.activity = _live_activity(raw, subject)
    else:
        for subject in subjects:
            subject.activity = _synced_activity(db, repo.id, subject, lo, hi)

    persona = personas.resolve(db, user, payload.persona_id)
    credential = credentials.resolve_credential(db, user)
    llm_budget.check_budget(db, user.user_id, kind=LLM_KIND_REPORT, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin)

    system_prompt = adhoc_prompts.build_system_prompt(persona)
    tokens = 0
    model = None
    for subject in subjects:
        if total_items(subject.activity) == 0:
            subject.section = _empty_section(subject, repo_name, payload.range_start, payload.range_end)
            continue
        # Per contributor, not once for the report: each section is its own call, and a
        # report naming eight people spends eight times. Checking only at the top would
        # let a report that starts inside the allowance finish well outside it.
        user_prompt = adhoc_prompts.build_user_prompt(_subject_payload(repo_name, payload.range_start, payload.range_end, subject))
        llm_budget.check_budget(
            db, user.user_id, kind=LLM_KIND_REPORT, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin,
            estimated_tokens=llm_budget.estimate_tokens([system_prompt, user_prompt]) + settings.AI_MAX_OUTPUT_TOKENS,
        )
        result = ai_provider.generate(
            system_prompt,
            user_prompt,
            max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            credential=credential,
        )
        subject.section = result.text
        model = result.model
        tokens += result.token_count or 0

    logger.info(
        "adhoc report: user=%s repo=%s mode=%s subjects=%s persona=%s key=%s model=%s tokens=%s",
        user.user_id, repo_name, "live" if live else "synced", len(subjects), persona.id,
        credential.source if credential else "none", model, tokens,
    )

    single = subjects[0] if len(subjects) == 1 else None
    report = Report(
        author_user_id=user.user_id,
        subject_user_id=single.user_id if single else None,
        subject_github_login=single.github_login if single else None,
        repo_id=repo.id if repo is not None else None,
        repo_full_name=repo_name,
        # Only a tracked repo carries a department, and the department is what routes a
        # report to its approvers. A live report on an untracked repo has none, so a
        # platform admin is its only approver — which is the honest answer, not a gap.
        dept_id=repo.dept_id if repo is not None else None,
        kind=REPORT_KIND_ADHOC,
        range_start=payload.range_start,
        range_end=payload.range_end,
        status=STATUS_DRAFT,
        summary_manager=_compile(subjects),
        generated_at=datetime.now(timezone.utc),
        prompt_version=adhoc_prompts.PROMPT_VERSION,
        persona_id=persona.id,
    )
    db.add(report)
    db.flush()
    for position, subject in enumerate(subjects):
        db.add(ReportSubject(
            report_id=report.id,
            subject_user_id=subject.user_id,
            subject_github_login=subject.github_login,
            section=subject.section,
            position=position,
        ))
    # The usage row goes in the SAME transaction as the report, for the reason
    # generation.py spells out: a second commit means a failed ledger write 500s a report
    # that was already saved, so the caller retries and pays for another generation.
    db.add(LlmUsage(report_id=report.id, kind=LLM_KIND_REPORT, user_id=user.user_id, dept_id=credentials.paying_dept_id(credential), tokens=tokens))
    db.commit()
    db.refresh(report)
    return report

"""
Rows are upserted by GitHub's own ids, so a re-run (including the overlap window
_commit_window re-requests) updates rather than duplicates. Every repo gets a
`sync_runs` row either way: "nothing happened" and "nothing was meant to happen" have
to be tellable apart.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable
import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from crescent_core import TokenClaims
from app import crypto
from app.config import settings
from app.models import Commit, GitHubAccount, Issue, PullRequest, Repository, Review, SyncRun
from app.services.github_client import GitHubClient, GitHubRateLimited
from app.services.leavers import revoke_departed_credentials
from app.services.repo_index import RECONNECT_DETAIL
from app.services.repositories import visible_repo_scope

logger = logging.getLogger(__name__)

class NoRepoAccess(Exception):
    """No connected account could open the repository. Almost always a private repo and
    tokens without the `repo` scope, so the run says what to do about it."""

def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def _as_utc(value: datetime | None) -> datetime | None:
    """Cursors are always written in UTC, but not every driver reads them back with a
    tzinfo. Without this a stored cursor can't be compared to a GitHub timestamp."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)

# "Merge pull request #12 from ..." and "Merge branch 'main' into ..." are GitHub's and
# git's own wording for a merge commit. Those commits carry no change of their own: the
# change is in the commits underneath, already attributed to whoever wrote them.
_MERGE_MESSAGE_RE = re.compile(r"^merge (pull request #\d+|branch |remote-tracking branch )")

# GitHub appends the pull request number to a squashed commit's subject, so the squash
# and the branch commit it absorbed differ by that suffix and nothing else.
_PR_NUMBER_SUFFIX_RE = re.compile(r"\s*\(#\d+\)\s*$")

def commit_author_login(payload: dict) -> str | None:
    """Who wrote the change, from GitHub's top-level `author`.

    GitHub sends `author` and `committer` separately, and a squash merge or a rebase
    makes them different people: `committer` is whoever pressed the merge button. There
    is deliberately no fallback to `committer` — a commit GitHub cannot match to an
    account is better left unattributed than credited to the person who merged it.
    """
    return ((payload.get("author") or {}).get("login")) or None

def commit_stamp(payload: dict) -> str | None:
    """When a commit landed on the branch, from GitHub's `commit.committer.date`.

    Not `commit.author.date`. Those two are the same for a commit pushed as written,
    and differ for a rebase, a cherry-pick or a squash: the author date is when the
    change was first written, the committer date is when this commit object was made,
    which is when it entered the branch. A report covering a week is a report of what
    arrived that week, so it reads the committer date, and the date-range filters read
    the same field. `author` is a fallback for a payload carrying no committer block.

    Both report paths call this so a repository cannot be dated one way when synced and
    another way when read live.
    """
    info = payload.get("commit") or {}
    return ((info.get("committer") or {}).get("date")) or ((info.get("author") or {}).get("date")) or None

def is_merge_commit_message(message: str | None) -> bool:
    return bool(_MERGE_MESSAGE_RE.match((message or "").strip().lower()))

def _subject(message: str | None) -> str:
    lines = (message or "").strip().splitlines()
    return lines[0] if lines else ""

def change_key(message: str | None) -> str:
    """A commit's subject line reduced to what a squash and its branch commits share."""
    return " ".join(_PR_NUMBER_SUFFIX_RE.sub("", _subject(message)).lower().split())

def has_pr_number(message: str | None) -> bool:
    return bool(_PR_NUMBER_SUFFIX_RE.search(_subject(message)))

def collapse_commits(items: list[dict]) -> tuple[list[dict], int, int]:
    """One change counted once, for a list of commits already narrowed to one author.

    Two things inflate a commit count. A merge commit is attributed to whoever merged,
    which puts somebody else's change under their name as well as the author's. And a
    squash merge repeats a change that is already present as the branch commit it
    absorbed, so the same work is counted twice under the author.

    The squash rule is narrow on purpose. GitHub writes a squashed commit's subject as
    the branch commit's subject with the pull request number appended, so two commits
    only collapse when one subject is exactly the other plus a "(#12)". Two commits that
    simply share a subject do not collapse: "update dev dependencies" every fortnight is
    a real commit every fortnight, and measured against pallets/flask the looser rule
    swallowed 74 of one maintainer's commits over twenty months. What this misses is the
    other direction — a squash of several commits with DIFFERENT subjects still counts
    once for the squash and once for each commit underneath.

    The first item wins, and callers pass commits newest first, so the squash on the
    default branch is what survives. Returns the kept commits and how many were dropped
    for each reason, because a report that quietly counted fewer commits than GitHub
    shows would be its own problem.

    This runs at reporting time, never at sync time: the rows are keyed by sha and every
    commit stays stored, so the raw history is still there to look at.
    """
    kept: list[dict] = []
    # subject with the number stripped -> whether the commits kept under it carried one.
    seen: dict[str, set[bool]] = {}
    merges = duplicates = 0
    for item in items:
        message = item.get("message")
        if is_merge_commit_message(message):
            merges += 1
            continue
        key = change_key(message)
        numbered = has_pr_number(message)
        # An empty subject carries nothing to compare, so those are all kept rather than
        # collapsed into one.
        if key and key in seen and numbered not in seen[key]:
            duplicates += 1
            continue
        if key:
            seen.setdefault(key, set()).add(numbered)
        kept.append(item)
    return kept, merges, duplicates

def collapse_note(merges: int, duplicates: int) -> str | None:
    parts = []
    if merges:
        parts.append(f"{merges} merge commit(s) were left out: a merge records who merged a change, not who wrote it")
    if duplicates:
        parts.append(f"{duplicates} commit(s) were counted once rather than twice, where a squashed commit repeats work already present as the branch commits it absorbed")
    if not parts:
        return None
    return "; ".join(parts) + "."

def _login_map(db: Session) -> dict[str, int]:
    return {a.github_login.lower(): a.user_id for a in db.scalars(select(GitHubAccount))}

def _attribute(login_map: dict[str, int], login: str | None, existing: int | None = None) -> int | None:
    """A login that no longer maps keeps whatever the row was already attributed to.
    Once a leaver's account is dropped their login falls out of the map, and GitHub
    re-lists old items whenever they're touched (a PR gets a comment, say), and that
    must not quietly blank out who wrote them."""
    return (login_map.get(login.lower()) if login else None) or existing

def _upsert_repository(db: Session, data: dict) -> Repository:
    repo = db.scalar(select(Repository).where(Repository.github_repo_id == data["id"]))
    if repo is None:
        repo = Repository(github_repo_id=data["id"])
        db.add(repo)
    # Only GitHub-owned metadata is refreshed; dept/lead/deputy/is_tracked/cursor
    # are ours and left untouched.
    repo.full_name = data["full_name"]
    repo.owner = data["owner"]["login"]
    repo.name = data["name"]
    repo.private = bool(data.get("private"))
    repo.default_branch = data.get("default_branch")
    return repo

def _sync_commits(db: Session, client, repo: Repository, login_map: dict[str, int], since: str | None, sha: str | None = None) -> int:
    n = 0
    for c in client.list_commits(repo.full_name, since=since, sha=sha):
        info = c.get("commit") or {}
        stamp = commit_stamp(c)
        login = commit_author_login(c)
        existing = db.scalar(select(Commit).where(Commit.repo_id == repo.id, Commit.sha == c["sha"]))
        commit = existing or Commit(repo_id=repo.id, sha=c["sha"])
        commit.author_github_login = login
        commit.author_user_id = _attribute(login_map, login, commit.author_user_id)
        commit.message = info.get("message")
        commit.url = c.get("html_url")
        commit.committed_at = _dt(stamp) or datetime.now(timezone.utc)
        if existing is None:
            db.add(commit)
        n += 1
    return n

def _sync_reviews(db: Session, client, full_name: str, pr: PullRequest, login_map: dict[str, int]) -> None:
    for r in client.list_reviews(full_name, pr.number):
        login = (r.get("user") or {}).get("login")
        existing = db.scalar(select(Review).where(Review.github_review_id == r["id"]))
        review = existing or Review(pull_request_id=pr.id, github_review_id=r["id"])
        review.reviewer_github_login = login
        review.reviewer_user_id = _attribute(login_map, login, review.reviewer_user_id)
        review.state = (r.get("state") or "").lower()
        review.submitted_at = _dt(r.get("submitted_at"))
        review.url = r.get("html_url")
        if existing is None:
            db.add(review)

def _sync_pull_requests(db: Session, client, repo: Repository, login_map: dict[str, int], since: datetime | None) -> int:
    n = 0
    for p in client.list_pull_requests(repo.full_name, since=since):
        login = (p.get("user") or {}).get("login")
        existing = db.scalar(select(PullRequest).where(PullRequest.github_pr_id == p["id"]))
        pr = existing or PullRequest(repo_id=repo.id, github_pr_id=p["id"])
        pr.number = p["number"]
        pr.title = p.get("title")
        pr.state = p.get("state")
        pr.merged = bool(p.get("merged_at"))
        pr.author_github_login = login
        pr.author_user_id = _attribute(login_map, login, pr.author_user_id)
        pr.gh_created_at = _dt(p.get("created_at"))
        pr.gh_updated_at = _dt(p.get("updated_at"))
        pr.merged_at = _dt(p.get("merged_at"))
        # Closed-and-merged and closed-without-merging are different outcomes, and only
        # closed_at dates the second one.
        pr.closed_at = _dt(p.get("closed_at"))
        pr.url = p.get("html_url")
        if existing is None:
            db.add(pr)
        db.flush()
        _sync_reviews(db, client, repo.full_name, pr, login_map)
        n += 1
    return n

def _sync_issues(db: Session, client, repo: Repository, login_map: dict[str, int], since: str | None) -> int:
    n = 0
    for i in client.list_issues(repo.full_name, since=since):
        if "pull_request" in i:
            continue  # GitHub's issues endpoint also returns PRs, so skip them
        login = (i.get("user") or {}).get("login")
        existing = db.scalar(select(Issue).where(Issue.github_issue_id == i["id"]))
        issue = existing or Issue(repo_id=repo.id, github_issue_id=i["id"])
        issue.number = i["number"]
        issue.title = i.get("title")
        issue.state = i.get("state")
        issue.author_github_login = login
        issue.author_user_id = _attribute(login_map, login, issue.author_user_id)
        # GitHub sends `assignees` as a list and `assignee` as the first of them. The
        # first is the one taken: a report describes one person's plan, and an issue
        # shared between three is not three separate intentions.
        assignee = ((i.get("assignee") or {}).get("login")) or None
        issue.assignee_github_login = assignee
        # Unassignment has to clear the id rather than keep the last one _attribute saw.
        # That fallback exists so a leaver keeps credit for what they wrote; an issue
        # taken off somebody is the opposite, a fact about who is NOT doing it.
        issue.assignee_user_id = _attribute(login_map, assignee) if assignee else None
        milestone = i.get("milestone") or {}
        issue.milestone_title = milestone.get("title")
        issue.milestone_due_on = _dt(milestone.get("due_on"))
        issue.gh_created_at = _dt(i.get("created_at"))
        issue.closed_at = _dt(i.get("closed_at"))
        issue.url = i.get("html_url")
        if existing is None:
            db.add(issue)
        n += 1
    return n

def _commit_window(cursor: datetime | None) -> datetime | None:
    """Commits are asked for from the cursor MINUS an overlap, because GitHub's `since`
    filters on commit date, not push time: an engineer who commits offline for a week
    and pushes today produces commits dated behind the cursor, which a window starting
    at the cursor would never return, and never would on any later run either. Re-asking
    for a window we mostly hold already is cheap: the rows upsert by (repo, sha)."""
    if cursor is None:
        return None
    return cursor - timedelta(minutes=settings.GITHUB_SYNC_OVERLAP_MINUTES)

def _pushed_since(data: dict, window_start: datetime | None) -> bool:
    pushed = _dt(data.get("pushed_at"))
    return window_start is None or pushed is None or pushed > window_start

def _sync_branches(db: Session, client, repo: Repository, login_map: dict[str, int], since: str | None) -> tuple[int, int]:
    n = scanned = 0
    for b in client.list_branches(repo.full_name):
        name, head = b.get("name"), (b.get("commit") or {}).get("sha")
        if not name or name == repo.default_branch:
            continue
        if head and db.scalar(select(Commit.id).where(Commit.repo_id == repo.id, Commit.sha == head)):
            continue
        n += _sync_commits(db, client, repo, login_map, since, sha=name)
        db.flush()
        scanned += 1
        if scanned >= settings.GITHUB_SYNC_MAX_BRANCHES:
            break
    return n, scanned

def _sync_one_repo(db: Session, client, data: dict, login_map: dict[str, int]) -> tuple[Repository, dict]:
    repo = _upsert_repository(db, data)
    db.flush()
    # Stamped before the fetch, not after, so anything landing mid-pass falls inside the
    # next run's window instead of into the gap between the fetch and the stamp.
    started = datetime.now(timezone.utc)
    cursor = _as_utc(repo.last_synced_at)
    window = _commit_window(cursor)
    since_str = window.isoformat() if window else None
    commits = branches = 0
    if _pushed_since(data, window):
        commits = _sync_commits(db, client, repo, login_map, since_str)
        db.flush()
        if settings.GITHUB_SYNC_BRANCHES:
            extra, branches = _sync_branches(db, client, repo, login_map, since_str)
            commits += extra
    # Pull requests and issues key off `updated_at`, which GitHub moves whenever the item
    # is touched, so the plain cursor is a sound filter for them and needs no overlap.
    counts = {
        "commits": commits,
        "branches": branches,
        "pull_requests": _sync_pull_requests(db, client, repo, login_map, cursor),
        "issues": _sync_issues(db, client, repo, login_map, cursor.isoformat() if cursor else None),
    }
    repo.last_synced_at = started
    return repo, counts

def _close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()

def _client_and_repo(make_client: Callable[[str], object], tokens: list[str], full_name: str):
    last_exc: Exception | None = None
    for token in tokens:
        client = make_client(token)
        try:
            return client, client.get_repo(full_name)
        except httpx.HTTPStatusError as exc:
            _close(client)
            if exc.response.status_code in (401, 403, 404):
                last_exc = exc
                continue
            raise
        except Exception:
            _close(client)
            raise
    if last_exc is not None:
        raise NoRepoAccess(f"{full_name} could not be read by any connected GitHub account. {RECONNECT_DETAIL}") from last_exc
    raise RuntimeError(f"no connected account can access {full_name}")

def run_full_sync(db: Session, make_client: Callable[[str], object] | None = None) -> list[SyncRun]:
    make_client = make_client or (lambda token: GitHubClient(token))
    runs: list[SyncRun] = []

    # Leavers first, before any token is decrypted, so this pass can't call GitHub with
    # a departed employee's credential.
    departed = revoke_departed_credentials(db)
    if departed:
        runs.append(_record(db, None, "success", "revoked stored GitHub credentials for departed user(s): " + ", ".join(str(u) for u in departed)))

    specs = settings.github_repos_list
    if not specs:
        # `detail` is served to platform admins over the API, so the variable an operator
        # has to set is named in the log only.
        logger.warning("sync had nothing to do: no repositories configured (set GITHUB_REPOS)")
        return runs + [_record(db, None, "success", "no repositories are configured to sync")]

    accounts = list(db.scalars(select(GitHubAccount).order_by(GitHubAccount.id)))
    if not accounts:
        return runs + [_record(db, None, "error", "no connected GitHub account to sync with")]
    tokens = [crypto.decrypt(a.access_token_encrypted) for a in accounts]
    login_map = _login_map(db)

    for full_name in specs:
        known = db.scalar(select(Repository).where(Repository.full_name == full_name))
        if known is not None and not known.is_tracked:
            runs.append(_record(db, known.id, "skipped", f"{full_name}: not tracked"))
            continue
        run = SyncRun(status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        client = None
        stage = "connecting to GitHub"
        try:
            client, data = _client_and_repo(make_client, tokens, full_name)
            stage = "reading repository activity"
            repo, counts = _sync_one_repo(db, client, data, login_map)
            run.repo_id = repo.id
            run.status = "success"
            run.detail = f"{full_name}: " + ", ".join(f"{k}={v}" for k, v in counts.items())
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except NoRepoAccess as exc:
            logger.warning("sync could not read %s with any connected account", full_name)
            db.rollback()
            run = db.get(SyncRun, run_id)
            run.status = "error"
            run.detail = str(exc)[:1000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except GitHubRateLimited as exc:
            logger.warning("sync rate-limited for %s: %s", full_name, exc)
            db.rollback()
            run = db.get(SyncRun, run_id)
            run.status = "rate_limited"
            run.detail = f"{full_name}: {exc}"[:1000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            # Whatever was raised can carry URLs, driver internals and library detail, and
            # this row is served to platform admins for as long as it is kept. The row keeps
            # what someone can act on (which repo, which stage, which run to look up); the
            # exception and its traceback go to the log.
            logger.exception("sync failed for %s while %s (sync_run id=%s)", full_name, stage, run_id)
            db.rollback()
            run = db.get(SyncRun, run_id)
            run.status = "error"
            run.detail = f"{full_name}: failed while {stage}; see the service log for sync run {run_id}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            _close(client)
        db.refresh(run)
        runs.append(run)
    return runs

def list_sync_runs(db: Session, user: TokenClaims, repo_id: int | None = None, limit: int = 50, offset: int = 0) -> tuple[list[SyncRun], int]:
    q = select(SyncRun)
    if repo_id is not None:
        q = q.where(SyncRun.repo_id == repo_id)
    if not user.is_platform_admin:
        q = q.join(Repository, Repository.id == SyncRun.repo_id).where(or_(*visible_repo_scope(user)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    q = q.options(joinedload(SyncRun.repository)).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
    return list(db.scalars(q.limit(limit).offset(offset))), total

def _record(db: Session, repo_id: int | None, status: str, detail: str) -> SyncRun:
    run = SyncRun(repo_id=repo_id, status=status, detail=detail, finished_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

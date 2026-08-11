"""
Rows are upserted by GitHub's own ids, so a re-run (including the overlap window
_commit_window re-requests) updates rather than duplicates. Every repo gets a
`sync_runs` row either way: "nothing happened" and "nothing was meant to happen" have
to be tellable apart.
"""
import logging
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
from app.services.repositories import visible_repo_scope

logger = logging.getLogger(__name__)

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
        stamp = (info.get("committer") or info.get("author") or {}).get("date")
        login = (c.get("author") or {}).get("login")
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
    raise last_exc or RuntimeError(f"no connected account can access {full_name}")

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
        return runs + [_record(db, None, "success", "no repos configured (set GITHUB_REPOS)")]

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
        try:
            client, data = _client_and_repo(make_client, tokens, full_name)
            repo, counts = _sync_one_repo(db, client, data, login_map)
            run.repo_id = repo.id
            run.status = "success"
            run.detail = f"{full_name}: " + ", ".join(f"{k}={v}" for k, v in counts.items())
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
        except Exception as exc:
            logger.exception("sync failed for %s", full_name)
            db.rollback()
            run = db.get(SyncRun, run_id)
            run.status = "error"
            run.detail = f"{full_name}: {exc}"[:1000]
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

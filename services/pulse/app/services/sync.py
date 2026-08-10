"""
For each repo in the allowlist, pull its commits, pull requests,
reviews and issues from GitHub and upsert them by GitHub's own ids (so re-runs
update rather than duplicate). Pulls are incremental. Activity is attributed to an identity user
when its GitHub login matches a connected account; otherwise just the login is
kept. Every repo gets a `sync_runs` row as a paper trail, including one saying it was
skipped for being untracked — "nothing happened" and "nothing was meant to happen"
have to be tellable apart.

A pass also starts by dropping the stored GitHub credentials of anyone identity now
reports as inactive (app/services/leavers.py) — the daily job is the natural place to
notice a leaver, and it means no pass ever calls GitHub with a departed employee's
token.

The Celery task in app/tasks.py calls `run_full_sync`. The GitHub calls go
through a `GitHubClient`, injected via `make_client`, so tests drive a fake.
"""
import logging
from datetime import datetime, timezone
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

def _login_map(db: Session) -> dict[str, int]:
    """github login (lowercased) → identity user_id, for attributing activity."""
    return {a.github_login.lower(): a.user_id for a in db.scalars(select(GitHubAccount))}

def _attribute(login_map: dict[str, int], login: str | None, existing: int | None = None) -> int | None:
    """A login that no longer maps keeps whatever the row was already attributed to.
    Once a leaver's account is dropped their login falls out of the map, and GitHub
    re-lists old items whenever they're touched (a PR gets a comment, say) — that
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

def _sync_commits(db: Session, client, repo: Repository, login_map: dict[str, int], since: str | None) -> int:
    n = 0
    for c in client.list_commits(repo.full_name, since=since):
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
        db.flush()  # need pr.id to attach its reviews
        _sync_reviews(db, client, repo.full_name, pr, login_map)
        n += 1
    return n

def _sync_issues(db: Session, client, repo: Repository, login_map: dict[str, int], since: str | None) -> int:
    n = 0
    for i in client.list_issues(repo.full_name, since=since):
        if "pull_request" in i:
            continue  # GitHub's issues endpoint also returns PRs — skip them
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

def _sync_one_repo(db: Session, client, data: dict, login_map: dict[str, int]) -> tuple[Repository, dict]:
    repo = _upsert_repository(db, data)
    db.flush()  # need repo.id for the child rows
    since_str = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    since_dt = repo.last_synced_at
    counts = {
        "commits": _sync_commits(db, client, repo, login_map, since_str),
        "pull_requests": _sync_pull_requests(db, client, repo, login_map, since_dt),
        "issues": _sync_issues(db, client, repo, login_map, since_str),
    }
    repo.last_synced_at = datetime.now(timezone.utc)
    return repo, counts

def _close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()

def _client_and_repo(make_client: Callable[[str], object], tokens: list[str], full_name: str):
    """Return a (client, repo_data) pair using the first connected account whose
    token can actually see the repo. Lets a private repo sync as long as *some*
    connected engineer has access, instead of failing on the first token."""
    last_exc: Exception | None = None
    for token in tokens:
        client = make_client(token)
        try:
            return client, client.get_repo(full_name)
        except httpx.HTTPStatusError as exc:
            _close(client)
            if exc.response.status_code in (401, 403, 404):
                last_exc = exc  # this account can't see it — try the next
                continue
            raise
        except Exception:
            # e.g. rate limited: no other token helps, so don't leak the http client.
            _close(client)
            raise
    raise last_exc or RuntimeError(f"no connected account can access {full_name}")

def run_full_sync(db: Session, make_client: Callable[[str], object] | None = None) -> list[SyncRun]:
    """One pass over the allowlist. Returns the SyncRun rows it wrote (one per
    repo, or a single explanatory row when there's nothing to do)."""
    make_client = make_client or (lambda token: GitHubClient(token))
    runs: list[SyncRun] = []

    # Leavers first, before any token is decrypted or sent to GitHub, so this pass
    # can't call GitHub with a departed employee's credential. This is the daily job's
    # to do because it already runs on a schedule, already lists the connected
    # accounts, and is already a write — a GET resolving a name is not the place to
    # delete rows.
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
        # Checked before any GitHub call, so an untracked repo costs no API quota. A
        # repo we've never synced has no row yet and so can't have been switched off.
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
            # Not a failure of ours — GitHub's quota is spent. Record it as its own
            # status with when it can resume, so "we were throttled" never reads as
            # "the sync is broken". The next scheduled pass picks the repo up again.
            logger.warning("sync rate-limited for %s: %s", full_name, exc)
            db.rollback()
            run = db.get(SyncRun, run_id)
            run.status = "rate_limited"
            run.detail = f"{full_name}: {exc}"[:1000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:  # one bad repo mustn't sink the whole run
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
    """Sync history for repos the caller can see, newest first — the answer to "why is
    my data stale?".

    Scoped with the same predicate as the repository list, via an inner join, so a run
    is visible exactly when its repo is. That join also drops the repo-less rows (the
    "no repos configured" / "no connected account" ones), which are platform-level
    config problems rather than anything a department can act on; a platform admin
    isn't filtered and still sees them."""
    q = select(SyncRun)
    if repo_id is not None:
        q = q.where(SyncRun.repo_id == repo_id)
    if not user.is_platform_admin:
        q = q.join(Repository, Repository.id == SyncRun.repo_id).where(or_(*visible_repo_scope(user)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    # started_at is second-resolution, so id breaks the tie within one pass.
    q = q.options(joinedload(SyncRun.repository)).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
    return list(db.scalars(q.limit(limit).offset(offset))), total

def _record(db: Session, repo_id: int | None, status: str, detail: str) -> SyncRun:
    run = SyncRun(repo_id=repo_id, status=status, detail=detail, finished_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

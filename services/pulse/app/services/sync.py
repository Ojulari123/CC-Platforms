"""The scheduled GitHub sync — service layer.

For each repo in the allowlist (`GITHUB_REPOS`), pull its commits, pull requests,
reviews and issues from GitHub and upsert them by GitHub's own ids (so re-runs
update rather than duplicate). Pulls are **incremental** — only what's changed
since the repo's `last_synced_at`. Activity is attributed to an identity user
when its GitHub login matches a connected account; otherwise just the login is
kept. Every repo gets a `sync_runs` row (success or error) as a paper trail.

The Celery task in app/tasks.py calls `run_full_sync`. The GitHub calls go
through a `GitHubClient`, injected via `make_client`, so tests drive a fake.
"""
import logging
from datetime import datetime, timezone
from typing import Callable
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import crypto
from app.config import settings
from app.models import Commit, GitHubAccount, Issue, PullRequest, Repository, Review, SyncRun
from app.services.github_client import GitHubClient

logger = logging.getLogger(__name__)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _login_map(db: Session) -> dict[str, int]:
    """github login (lowercased) → identity user_id, for attributing activity."""
    return {a.github_login.lower(): a.user_id for a in db.scalars(select(GitHubAccount))}


def _attribute(login_map: dict[str, int], login: str | None) -> int | None:
    return login_map.get(login.lower()) if login else None


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
        commit.author_user_id = _attribute(login_map, login)
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
        review.reviewer_user_id = _attribute(login_map, login)
        review.state = (r.get("state") or "").lower()
        review.submitted_at = _dt(r.get("submitted_at"))
        review.url = r.get("html_url")
        if existing is None:
            db.add(review)


def _sync_pull_requests(db: Session, client, repo: Repository, login_map: dict[str, int]) -> int:
    n = 0
    for p in client.list_pull_requests(repo.full_name):
        login = (p.get("user") or {}).get("login")
        existing = db.scalar(select(PullRequest).where(PullRequest.github_pr_id == p["id"]))
        pr = existing or PullRequest(repo_id=repo.id, github_pr_id=p["id"])
        pr.number = p["number"]
        pr.title = p.get("title")
        pr.state = p.get("state")
        pr.merged = bool(p.get("merged_at"))
        pr.author_github_login = login
        pr.author_user_id = _attribute(login_map, login)
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
        issue.author_user_id = _attribute(login_map, login)
        issue.gh_created_at = _dt(i.get("created_at"))
        issue.closed_at = _dt(i.get("closed_at"))
        issue.url = i.get("html_url")
        if existing is None:
            db.add(issue)
        n += 1
    return n


def _sync_one_repo(db: Session, client, full_name: str, login_map: dict[str, int]) -> tuple[Repository, dict]:
    repo = _upsert_repository(db, client.get_repo(full_name))
    db.flush()  # need repo.id for the child rows
    since = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    counts = {
        "commits": _sync_commits(db, client, repo, login_map, since),
        "pull_requests": _sync_pull_requests(db, client, repo, login_map),
        "issues": _sync_issues(db, client, repo, login_map, since),
    }
    repo.last_synced_at = datetime.now(timezone.utc)
    return repo, counts


def run_full_sync(db: Session, make_client: Callable[[str], object] | None = None) -> list[SyncRun]:
    """One pass over the allowlist. Returns the SyncRun rows it wrote (one per
    repo, or a single explanatory row when there's nothing to do)."""
    make_client = make_client or (lambda token: GitHubClient(token))
    specs = settings.github_repos_list
    if not specs:
        return [_record(db, None, "success", "no repos configured (set GITHUB_REPOS)")]

    account = db.scalar(select(GitHubAccount).order_by(GitHubAccount.id).limit(1))
    if account is None:
        return [_record(db, None, "error", "no connected GitHub account to sync with")]

    client = make_client(crypto.decrypt(account.access_token_encrypted))
    login_map = _login_map(db)
    runs: list[SyncRun] = []
    try:
        for full_name in specs:
            run = SyncRun(status="running")
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id
            try:
                repo, counts = _sync_one_repo(db, client, full_name, login_map)
                run.repo_id = repo.id
                run.status = "success"
                run.detail = f"{full_name}: " + ", ".join(f"{k}={v}" for k, v in counts.items())
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
            db.refresh(run)
            runs.append(run)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return runs


def _record(db: Session, repo_id: int | None, status: str, detail: str) -> SyncRun:
    run = SyncRun(repo_id=repo_id, status=status, detail=detail, finished_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

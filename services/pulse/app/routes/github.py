"""
Connect / view / disconnect a GitHub account for the signed-in user.

Thin routes to verify who's calling, and hand off to app/services/github_oauth. The
one exception to auth is the OAuth callback, which GitHub calls as a plain
browser redirect. Its trust comes from the signed `state`, not a token.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.auth import current_user
from app.db import get_db
from app.rate_limit import limiter
from app.schemas.github import GitHubAccountResponse, GitHubConnectResponse
from app.services import github_oauth
from app.services import sync as sync_service
from app.tasks import sync_all_repos

router = APIRouter(prefix="/github", tags=["github"])

@router.get("/connect", response_model=GitHubConnectResponse)
@limiter.limit("10/minute")
def connect(request: Request, user: TokenClaims = Depends(current_user)) -> GitHubConnectResponse:
    """Start connecting the caller's GitHub account. Returns the URL to send the
    browser to; the callback carries a signed state so we know it's this user."""
    return GitHubConnectResponse(authorize_url=github_oauth.build_authorize_url(user.user_id))

@router.get("/oauth/callback", response_class=HTMLResponse)
@limiter.limit("20/minute")
def oauth_callback(request: Request, code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)) -> HTMLResponse:
    """GitHub redirects the browser here after the user authorizes. No auth
    header — the identity user id travels in `state`. There's no frontend to land
    on until Week 5, so we return a tiny confirmation page."""
    account = github_oauth.handle_callback(db, code, state)
    return HTMLResponse(
        f"<h3>GitHub connected as @{account.github_login}</h3>"
        "<p>You can close this tab and go back to Pulse.</p>"
    )

@router.get("/account", response_model=GitHubAccountResponse)
def my_account(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> GitHubAccountResponse:
    """The caller's connected GitHub account, or 404 if they haven't connected one."""
    account = github_oauth.get_account(db, user.user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No GitHub account connected")
    return account


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Disconnect the caller's GitHub account. Idempotent."""
    github_oauth.disconnect(db, user.user_id)

@router.post("/sync")
@limiter.limit("5/minute")
def trigger_sync(request: Request, wait: bool = Query(default=False, description="Run inline and return results (dev/demo). Default enqueues to the Celery worker."), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Run a sync now instead of waiting for the daily job. Admin-only. By default
    it enqueues the Celery task (non-blocking) and returns the task id; pass
    `?wait=true` to run one pass inline and get the per-repo results back."""
    if not (user.is_platform_admin or any(m.role == "admin" for m in user.memberships)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin can trigger a sync")
    if wait:
        runs = sync_service.run_full_sync(db)
        return {"mode": "inline", "runs": [{"repo_id": r.repo_id, "status": r.status, "detail": r.detail} for r in runs]}
    task = sync_all_repos.delay()
    return {"mode": "queued", "task_id": task.id}

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.config import settings
from app.db import get_db
from app.rate_limit import address_key, limiter, user_or_address_key
from app.schemas.github import GitHubAccountResponse, GitHubConnectResponse, SyncRunResponse
from app.services import github_oauth
from app.services import sync as sync_service
from app.tasks import sync_all_repos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

CONNECT_OUTCOMES = frozenset({"connected", "denied", "expired", "already_linked", "not_configured", "failed"})
_OUTCOME_BY_STATUS = {400: "expired", 409: "already_linked", 503: "not_configured"}

@router.get("/connect", response_model=GitHubConnectResponse)
@limiter.limit("10/minute", key_func=user_or_address_key)
def connect(request: Request, user: TokenClaims = Depends(current_user)) -> GitHubConnectResponse:
    return GitHubConnectResponse(authorize_url=github_oauth.build_authorize_url(user.user_id))

def _back_to_pulse(outcome: str) -> RedirectResponse:
    """The target is built only from settings and a fixed outcome code: nothing from
    the request reaches it, so this callback can never be turned into an open redirect."""
    if outcome not in CONNECT_OUTCOMES:
        outcome = "failed"
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/?github={outcome}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.get("/oauth/callback", response_class=RedirectResponse)
@limiter.limit("20/minute", key_func=address_key)
def oauth_callback(request: Request, code: str | None = Query(default=None), state: str | None = Query(default=None), error: str | None = Query(default=None), db: Session = Depends(get_db)) -> RedirectResponse:
    """No auth header: the identity user id travels in `state`, and the signature on
    `state` is the only thing authenticating this request. Every outcome ends in a
    redirect because a person in a browser has nowhere to go from an error page here."""
    if error or not code or not state:
        return _back_to_pulse("denied" if error == "access_denied" else "failed")
    try:
        github_oauth.handle_callback(db, code, state)
    except HTTPException as exc:
        logger.warning("GitHub OAuth callback rejected: %s %s", exc.status_code, exc.detail)
        return _back_to_pulse(_OUTCOME_BY_STATUS.get(exc.status_code, "failed"))
    except httpx.HTTPError as exc:
        logger.warning("GitHub OAuth callback could not reach GitHub: %s", exc)
        return _back_to_pulse("failed")
    return _back_to_pulse("connected")

@router.get("/account", response_model=GitHubAccountResponse)
def my_account(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> GitHubAccountResponse:
    account = github_oauth.get_account(db, user.user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No GitHub account connected")
    return account


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    github_oauth.disconnect(db, user.user_id)

@router.post("/sync")
@limiter.limit("5/minute", key_func=user_or_address_key)
def trigger_sync(request: Request, wait: bool = Query(default=False, description="Run inline and return results (dev/demo). Default enqueues to the Celery worker."), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a platform admin can trigger a sync")
    if wait:
        runs = sync_service.run_full_sync(db)
        return {"mode": "inline", "runs": [{"repo_id": r.repo_id, "status": r.status, "detail": r.detail} for r in runs]}
    task = sync_all_repos.delay()
    return {"mode": "queued", "task_id": task.id}

@router.get("/sync-runs", response_model=Page[SyncRunResponse])
def list_sync_runs(repo_id: int | None = Query(default=None, description="Only this repo's history."), page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[SyncRunResponse]:
    runs, total = sync_service.list_sync_runs(db, user, repo_id=repo_id, limit=page.limit, offset=page.offset)
    return Page.of([SyncRunResponse.of(r) for r in runs], total=total, params=page)

import logging
import secrets
from urllib.parse import urlencode
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import crypto
from app.config import settings
from app.models import GitHubAccount

logger = logging.getLogger(__name__)

STATE_MAX_AGE_SECONDS = 600

def _require_oauth_configured() -> None:
    # GITHUB_TOKEN_ENC_KEY is checked here too: both entry points sign or read a `state`
    # with it, and without this the missing key surfaced as an unhandled 500 from crypto
    # instead of a handled "this server isn't set up".
    missing = [
        name for name, value in (
            ("GITHUB_CLIENT_ID", settings.GITHUB_CLIENT_ID),
            ("GITHUB_CLIENT_SECRET", settings.GITHUB_CLIENT_SECRET),
            ("GITHUB_TOKEN_ENC_KEY", settings.GITHUB_TOKEN_ENC_KEY),
        ) if not value
    ]
    if missing:
        # Which variable is missing is an operator's problem, so it goes in the log. The
        # caller gets something they can act on without learning how we're configured.
        logger.error(
            "GitHub is not configured: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET and GITHUB_TOKEN_ENC_KEY must all be set (missing: %s)",
            ", ".join(missing),
        )
        raise HTTPException(
            status_code=503,
            detail="GitHub is not set up on this server. Contact an admin.",
        )

def build_authorize_url(user_id: int) -> str:
    _require_oauth_configured()
    state = crypto.sign_state({"uid": user_id, "nonce": secrets.token_urlsafe(8)})
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        "scope": settings.GITHUB_OAUTH_SCOPES,
        "state": state,
        "allow_signup": "false",
    }
    return f"{settings.GITHUB_OAUTH_BASE}/login/oauth/authorize?{urlencode(params)}"

def exchange_code_for_token(code: str) -> str:
    resp = httpx.post(
        f"{settings.GITHUB_OAUTH_BASE}/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body.get("access_token")
    if not token:
        reason = body.get("error_description") or body.get("error") or "no access_token returned"
        raise HTTPException(status_code=502, detail=f"GitHub rejected the authorization: {reason}")
    return token

def fetch_github_user(token: str) -> dict:
    resp = httpx.get(
        f"{settings.GITHUB_API_URL}/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()

def handle_callback(db: Session, code: str, state: str) -> GitHubAccount:
    _require_oauth_configured()
    try:
        payload = crypto.read_state(state, STATE_MAX_AGE_SECONDS)
    except crypto.InvalidStateError:
        raise HTTPException(status_code=400, detail="Invalid or expired connect link. Start again from /github/connect")
    user_id = int(payload["uid"])

    token = exchange_code_for_token(code)
    gh = fetch_github_user(token)

    account = db.scalar(select(GitHubAccount).where(GitHubAccount.user_id == user_id))
    if account is None:
        account = GitHubAccount(user_id=user_id)
        db.add(account)
    account.github_user_id = int(gh["id"])
    account.github_login = gh["login"]
    account.access_token_encrypted = crypto.encrypt(token)
    account.scopes = settings.GITHUB_OAUTH_SCOPES
    try:
        db.commit()
    except IntegrityError:
        # github_user_id is unique: this GitHub identity is already linked to a
        # different platform user.
        db.rollback()
        raise HTTPException(status_code=409, detail="That GitHub account is already connected to another user")
    db.refresh(account)
    return account

def has_repo_scope(account: GitHubAccount | None) -> bool:
    """Whether the stored token can read private repository contents. `scopes` records
    what was asked for at connect time, so an account connected before
    GITHUB_OAUTH_SCOPES was widened still reads false — which is right, its token really
    doesn't have it, and the API says so instead of failing at fetch time."""
    if account is None or not account.scopes:
        return False
    granted = {s.strip() for s in account.scopes.split(",") if s.strip()}
    return "repo" in granted

def get_account(db: Session, user_id: int) -> GitHubAccount | None:
    return db.scalar(select(GitHubAccount).where(GitHubAccount.user_id == user_id))

def disconnect(db: Session, user_id: int) -> None:
    account = get_account(db, user_id)
    if account:
        db.delete(account)
        db.commit()

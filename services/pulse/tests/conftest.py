import os
from cryptography.fernet import Fernet as _Fernet # fixed dummy id/secret and a fresh Fernet key so the connect flow works without real credentials.
import httpx
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from crescent_core import TokenClaims

# Every setting app/config.py declares is pinned here, assigned not setdefault, so .env
# and exported shell vars can't change a test result. Credentials stay blank on purpose:
# a test that wants the identity or email path stubs it, as the existing ones do.
_ambient_db_url = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IDENTITY_JWKS_URL"] = "http://identity-not-called/.well-known/jwks.json"
os.environ["IDENTITY_API_URL"] = "http://identity-not-called:8000"
os.environ["PULSE_SERVICE_CLIENT_ID"] = "pulse"
os.environ["PULSE_SERVICE_CLIENT_SECRET"] = ""
os.environ["JWT_ISSUER"] = "cyphercrescent-identity"
os.environ["JWKS_TTL_SECONDS"] = "3600"
os.environ["TOKEN_VERSION_TTL_SECONDS"] = "60"
os.environ["CORS_ORIGINS"] = "http://localhost:3000,http://localhost:3001"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # don't throttle the test client
os.environ["TRUST_PROXY_HEADERS"] = "false"
os.environ["TRUSTED_PROXY_COUNT"] = "1"
os.environ["REDIS_URL"] = "redis://redis-not-called:6379/0"
os.environ["SYNC_HOUR_UTC"] = "2"
os.environ["GITHUB_CLIENT_ID"] = "test-client-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-client-secret"
os.environ["GITHUB_OAUTH_REDIRECT_URI"] = "http://localhost:8002/github/oauth/callback"
os.environ["GITHUB_OAUTH_SCOPES"] = "read:user"
os.environ["GITHUB_OAUTH_BASE"] = "https://github.com"
os.environ["GITHUB_API_URL"] = "https://api.github-not-called.test"
os.environ["GITHUB_TOKEN_ENC_KEY"] = _Fernet.generate_key().decode()
os.environ["GITHUB_REPOS"] = ""
# OPENAI_API_KEY too: config.py accepts either name for the one LLM_API_KEY setting.
os.environ["LLM_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["LLM_MODEL"] = "gpt-4o-mini"
os.environ["LLM_TIMEOUT_SECONDS"] = "30.0"
os.environ["LLM_MAX_OUTPUT_TOKENS"] = "1000"
os.environ["BREVO_API_KEY"] = ""
os.environ["EMAIL_FROM"] = ""
os.environ["FRONTEND_URL"] = "http://localhost:3000"

if _ambient_db_url and _ambient_db_url != "sqlite:///:memory:":

    def pytest_report_header():
        return "conftest: exported DATABASE_URL ignored; tests always use in-memory SQLite"

# Blank credentials make an outbound call useless; this makes it impossible. Only the
# socket-backed transports are replaced, so TestClient and MockTransport still work.
# Attempts are recorded too, since the notify path swallows every exception.
BLOCKED_REQUESTS: list[str] = []

def _block(request) -> None:
    BLOCKED_REQUESTS.append(f"{request.method} {request.url}")
    raise RuntimeError(f"Outbound HTTP blocked in tests: {request.method} {request.url}")

def _blocked_handle_request(self, request):
    _block(request)

async def _blocked_handle_async_request(self, request):
    _block(request)

httpx.HTTPTransport.handle_request = _blocked_handle_request
httpx.AsyncHTTPTransport.handle_async_request = _blocked_handle_async_request

from app.auth import current_user
from app.db import Base, get_db
from app.main import app
from app.services import identity_client

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


_active: dict = {"claims": None}

def _override_current_user() -> TokenClaims:
    if _active["claims"] is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _active["claims"]

app.dependency_overrides[get_db] = _override_get_db
app.dependency_overrides[current_user] = _override_current_user

@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(_engine)
    # The profile cache is process-global with a 5-minute TTL, so without this a name
    # resolved in one test would still be served in the next.
    identity_client.clear_profile_cache()
    BLOCKED_REQUESTS.clear()
    yield
    Base.metadata.drop_all(_engine)
    identity_client.clear_profile_cache()
    _active["claims"] = None
    # Fails the test that tried, even if its own code swallowed the error.
    assert not BLOCKED_REQUESTS, f"test attempted outbound HTTP: {BLOCKED_REQUESTS}"

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def db():
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def act_as():

    def _set(user_id: int, *, memberships=(), leads=(), is_platform_admin: bool = False, email: str = "u@x.com") -> TokenClaims:
        claims = TokenClaims.from_payload({
            "sub": str(user_id),
            "email": email,
            "memberships": [dict(m) for m in memberships],
            "leads": list(leads),
            "is_platform_admin": is_platform_admin,
            "tv": 0,
        })
        _active["claims"] = claims
        return claims

    return _set

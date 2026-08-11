import os
import httpx
import pytest
from fastapi import Depends, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from crescent_core import TokenClaims

# Every setting app/config.py declares is pinned here, assigned not setdefault, so .env
# and exported shell vars can't change a test result. An exported DATABASE_URL (Neon,
# local Postgres) would otherwise bind app.db.engine to a real database for the whole
# run, and an exported IDENTITY_API_URL would point the revocation check (which runs on
# every authenticated request) at a live identity. The service secret stays blank on
# purpose: a test that wants that path stubs it, as test_revocation does.
_ambient_db_url = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IDENTITY_JWKS_URL"] = "http://identity-not-called/.well-known/jwks.json"
os.environ["IDENTITY_API_URL"] = "http://identity-not-called:8000"
os.environ["FORGE_SERVICE_CLIENT_ID"] = "forge"
os.environ["FORGE_SERVICE_CLIENT_SECRET"] = ""
os.environ["TOKEN_VERSION_TTL_SECONDS"] = "60"
os.environ["JWT_ISSUER"] = "cyphercrescent-identity"
os.environ["JWKS_TTL_SECONDS"] = "3600"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # don't throttle the test client
# Blank, not a dummy host: app.rate_limit probes this store at import time, and a URL
# with a hostname makes that a real DNS lookup and connect attempt from the test run.
os.environ["REDIS_URL"] = ""
os.environ["TRUST_PROXY_HEADERS"] = "false"
os.environ["TRUSTED_PROXY_COUNT"] = "1"
os.environ["DATASET_PREVIEW_ROWS"] = "10"
os.environ["MAX_UPLOAD_MB"] = "5"

if _ambient_db_url and _ambient_db_url != "sqlite:///:memory:":

    def pytest_report_header():
        return "conftest: exported DATABASE_URL ignored; tests always use in-memory SQLite"

# A blank client secret makes an outbound call useless; this makes it impossible. Only
# the socket-backed transports are replaced, so TestClient's ASGITransport and any
# MockTransport still work. Attempts are recorded too, since the revocation checker
# swallows every exception and degrades to "unchecked".
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

# Test-only endpoint: proves the auth dependency is wired and that the override
# above actually intercepts it.
@app.get("/_whoami")
def _whoami(user: TokenClaims = Depends(current_user)):
    return {"user_id": user.user_id}

@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(_engine)
    BLOCKED_REQUESTS.clear()
    yield
    Base.metadata.drop_all(_engine)
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
def test_sessionmaker():
    return _TestSession

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

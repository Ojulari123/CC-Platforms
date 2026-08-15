import os
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_keys_dir = tempfile.mkdtemp(prefix="identity_test_keys_")
_priv_path = os.path.join(_keys_dir, "private.pem")
_pub_path = os.path.join(_keys_dir, "public.pem")

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
with open(_priv_path, "wb") as f:
    f.write(
        _private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
with open(_pub_path, "wb") as f:
    f.write(
        _private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

_retired_dir = os.path.join(_keys_dir, "retired")
os.makedirs(_retired_dir, exist_ok=True)

# Every setting app/config.py declares is pinned here, assigned not setdefault, so .env
# and exported shell vars can't change a test result. Credentials stay blank on purpose:
# a test that wants the email path stubs it, as the existing ones do.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_PRIVATE_KEY_PATH"] = _priv_path
os.environ["JWT_PUBLIC_KEY_PATH"] = _pub_path
# Empty on purpose: no retired key verifies anything unless a test puts one there.
os.environ["JWT_RETIRED_PUBLIC_KEYS_DIR"] = _retired_dir
os.environ["JWT_ALGORITHM"] = "RS256"
os.environ["JWT_ISSUER"] = "cyphercrescent-identity"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["SERVICE_TOKEN_EXPIRE_MINUTES"] = "10"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
os.environ["CORS_ORIGINS"] = "http://localhost:3000,http://localhost:3001"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # don't throttle the test client
# Blank, not a dummy host: app.rate_limit probes this store at import time, and a URL
# with a hostname makes that a real DNS lookup and connect attempt from the test run.
os.environ["REDIS_URL"] = ""
os.environ["TRUST_PROXY_HEADERS"] = "false"
os.environ["TRUSTED_PROXY_COUNT"] = "1"
os.environ["BREVO_API_KEY"] = ""
os.environ["EMAIL_FROM"] = ""
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ["INVITE_EXPIRE_DAYS"] = "7"
os.environ["PASSWORD_RESET_EXPIRE_MINUTES"] = "30"
# The .env this service reads now locks signup to one domain. Tests set the allowlist
# they need per case, so the starting state stays "empty = any domain".
os.environ["SIGNUP_ALLOWED_DOMAINS"] = ""
os.environ["PULSE_CLIENT_ID"] = "pulse"
os.environ["FORGE_CLIENT_ID"] = "forge"
# Leave the startup seed a no-op. The lifespan seeds through app.db.SessionLocal,
# which is NOT the overridden test engine, so a configured secret makes any test
# that enters the lifespan hit an empty database. Seed tests set this themselves.
os.environ["PULSE_CLIENT_SECRET"] = ""
os.environ["FORGE_CLIENT_SECRET"] = ""

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

from app.db import Base, get_db
from app.main import app
from app.services import email as email_service

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

app.dependency_overrides[get_db] = _override_get_db

@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(_engine)
    BLOCKED_REQUESTS.clear()
    yield
    Base.metadata.drop_all(_engine)
    # Fails the test that tried, even if its own code swallowed the error.
    assert not BLOCKED_REQUESTS, f"test attempted outbound HTTP: {BLOCKED_REQUESTS}"

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def db_session():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def sent_emails(monkeypatch):
    captured = []

    def fake_send_invite(to, dept_name, role, raw_token, team_name=None):
        captured.append({
            "to": to, "dept_name": dept_name, "team_name": team_name,
            "role": role, "raw_token": raw_token,
        })

    monkeypatch.setattr(email_service, "send_invite", fake_send_invite)
    return captured


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def refreshed(client: TestClient, tokens: dict) -> dict:
    """What a client does for itself after a 401: swap the refresh token for a new pair.
    A membership change bumps token_version and kills the access token, and this is the
    step that picks the corrected claims up without anyone logging in again."""
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    password = "Test123!password"
    resp = client.post(
        "/auth/register",
        json={
            "email": "alice@example.com",
            "password": password,
            "first_name": "Alice",
            "last_name": "Anderson",
            "dept_name": "Engineering",
        },
    )
    assert resp.status_code == 201, resp.text
    tokens = resp.json()
    dept_id = client.get("/me", headers=auth(tokens)).json()["memberships"][0]["dept_id"]
    return {"tokens": tokens, "password": password, "email": "alice@example.com", "dept_id": dept_id}

@pytest.fixture
def invite_user(client: TestClient, sent_emails: list):
    def _invite(
        inviter_tokens: dict,
        dept_id: int,
        email: str,
        role: str = "engineer",
        team_id: int | None = None,
        password: str = "Test123!password",
    ) -> dict:
        r = client.post(
            f"/departments/{dept_id}/invites",
            json={"email": email, "role": role, "team_id": team_id},
            headers=auth(inviter_tokens),
        )
        assert r.status_code == 201, r.text
        resp = client.post("/invites/accept", json={
            "token": sent_emails[-1]["raw_token"],
            "first_name": email.split("@")[0].title(),
            "last_name": "Tester",
            "password": password,
        })
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _invite

@pytest.fixture
def engineer_user(client: TestClient, registered_user: dict, invite_user) -> dict:
    return invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")

@pytest.fixture
def second_dept(client: TestClient, registered_user: dict) -> int:
    r = client.post("/departments", json={"name": "Data"}, headers=auth(registered_user["tokens"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]

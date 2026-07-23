"""Test bootstrap: generates an ephemeral RSA keypair and points the app at
SQLite in-memory before any app modules import their settings."""
import os
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_PRIVATE_KEY_PATH"] = _priv_path
os.environ["JWT_PUBLIC_KEY_PATH"] = _pub_path
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
# Off globally so unrelated tests can hammer /auth/* freely; the dedicated
# rate-limit test flips limiter.enabled on for itself only.
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Blank out email creds so tests can NEVER hit Brevo, even with a real key in
# .env (env vars beat the .env file in pydantic-settings). Tests monkeypatch
# email_service.send_invite to capture invites instead.
os.environ["BREVO_API_KEY"] = ""
os.environ["EMAIL_FROM"] = ""

# ------- noqa: E402 -------
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    yield
    Base.metadata.drop_all(_engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture outgoing invites instead of calling Brevo. Each entry carries the
    raw token, which is the only place it ever exists outside the email."""
    captured = []

    def fake_send_invite(to, dept_name, role, raw_token):
        captured.append({"to": to, "dept_name": dept_name, "role": role, "raw_token": raw_token})

    monkeypatch.setattr(email_service, "send_invite", fake_send_invite)
    return captured


def auth(tokens: dict) -> dict:
    """Authorization header from any token-pair response."""
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    """The bootstrap user: first registration, so platform admin + admin of the
    first department ('Engineering'). Registration is closed after this, which
    is why every other user in these tests arrives by invite."""
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
    """Invite someone into a department and accept it — returns their token pair.
    The only way to add people now that self-signup is closed."""

    def _invite(inviter_tokens: dict, dept_id: int, email: str, role: str = "engineer", team_id: int | None = None) -> dict:
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
            "password": "Test123!password",
        })
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _invite


@pytest.fixture
def engineer_user(client: TestClient, registered_user: dict, invite_user) -> dict:
    """A second user in the SAME department as registered_user, role=engineer.
    Not a platform admin — this is the fixture that proves role gating bites."""
    return invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")


@pytest.fixture
def second_dept(client: TestClient, registered_user: dict) -> int:
    """A second department, created by the platform admin. Returns its id."""
    r = client.post("/departments", json={"name": "Data"}, headers=auth(registered_user["tokens"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]

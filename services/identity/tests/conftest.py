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
def registered_user(client: TestClient) -> dict:
    """Register a user and return {'tokens': <register response>, 'password': ...}."""
    password = "Test123!password"
    resp = client.post(
        "/auth/register",
        json={
            "email": "alice@example.com",
            "password": password,
            "first_name": "Alice",
            "last_name": "Anderson",
            "org_name": "Acme Corp",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"tokens": resp.json(), "password": password, "email": "alice@example.com"}

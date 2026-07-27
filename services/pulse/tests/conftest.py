"""Test bootstrap for Pulse.

In-memory SQLite, and the auth dependency is overridden so tests inject
`TokenClaims` directly. Token *verification* (signature/expiry/issuer) is already
covered by packages/core and the cross-service contract tests; what Pulse's own
suite exercises is the report domain and its authorization rules, driven off the
claims a verified token would carry.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("IDENTITY_JWKS_URL", "http://identity-not-called/.well-known/jwks.json")

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from crescent_core import TokenClaims

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


# Whoever the current request is acting as. Set by the `act_as` fixture; None
# means "no valid token", which the override turns into a 401.
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
    yield
    Base.metadata.drop_all(_engine)
    _active["claims"] = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def act_as():
    """Set the caller for subsequent requests, the way a verified token would.
    Returns the claims so a test can read back user_id etc."""

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

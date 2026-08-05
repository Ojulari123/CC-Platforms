import pytest
from app.rate_limit import limiter

@pytest.fixture
def rate_limited():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False

def test_login_returns_429_after_10_attempts(client, rate_limited):
    payload = {"email": "ghost@example.com", "password": "Wrong123!pass"}
    for _ in range(10):
        r = client.post("/auth/login", json=payload)
        assert r.status_code == 401  # wrong creds, but not throttled yet
    r = client.post("/auth/login", json=payload)
    assert r.status_code == 429

def _register(client, i):
    return client.post("/auth/register", json={
        "email": f"user{i}@example.com",
        "password": "Test123!password",
        "first_name": "U",
        "last_name": "Ser",
        "dept_name": f"Department {i}",
    })

def test_register_returns_429_after_5_attempts(client, rate_limited):
    """The limiter counts ATTEMPTS, not successes. Registration is bootstrap-only
    now, so only the first call succeeds — but the remaining rejected ones still
    burn quota, which is exactly what stops someone hammering the endpoint."""
    assert _register(client, 0).status_code == 201  # bootstrap
    for i in range(1, 5):
        assert _register(client, i).status_code == 403  # closed, but still counted
    assert _register(client, 6).status_code == 429


def test_limits_do_not_leak_into_other_tests(client):
    # limiter.enabled is False again here — 11 logins, no 429.
    payload = {"email": "ghost@example.com", "password": "Wrong123!pass"}
    for _ in range(11):
        r = client.post("/auth/login", json=payload)
        assert r.status_code == 401

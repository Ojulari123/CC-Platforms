"""Rate limiting is disabled globally in conftest (RATE_LIMIT_ENABLED=false)
so the rest of the suite can hit /auth/* freely. These tests flip the limiter
on for themselves, then reset it so nothing leaks across tests."""
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


def test_register_returns_429_after_5_attempts(client, rate_limited):
    for i in range(5):
        r = client.post("/auth/register", json={
            "email": f"user{i}@example.com",
            "password": "Test123!password",
            "first_name": "U",
            "last_name": "Ser",
            "org_name": f"Org {i}",
        })
        assert r.status_code == 201
    r = client.post("/auth/register", json={
        "email": "user6@example.com",
        "password": "Test123!password",
        "first_name": "U",
        "last_name": "Ser",
        "org_name": "Org 6",
    })
    assert r.status_code == 429


def test_limits_do_not_leak_into_other_tests(client):
    # limiter.enabled is False again here — 11 logins, no 429.
    payload = {"email": "ghost@example.com", "password": "Wrong123!pass"}
    for _ in range(11):
        r = client.post("/auth/login", json=payload)
        assert r.status_code == 401

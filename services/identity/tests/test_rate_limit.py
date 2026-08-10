import time
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from limits.storage import memory as limits_memory
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from pydantic import ValidationError
from app import rate_limit
from app.config import Settings, settings
from app.rate_limit import limiter, user_or_address_key
from tests.conftest import auth

class _FrozenClock:
    """Stands in for the `time` module inside the limiter's in-memory storage."""

    def __init__(self, now):
        self._now = now

    def time(self):
        return self._now

@pytest.fixture(autouse=True)
def _deterministic_limiter(monkeypatch):
    # A window opens on a key's first hit and closes a minute of real time later, so on
    # a slow enough run the allowance a test just spent expires before the request that
    # is meant to be refused. Frozen, only requests can spend a window.
    monkeypatch.setattr(limits_memory, "time", _FrozenClock(time.time()))
    # The flip side: a window now never expires on its own. A test that wants to watch
    # one lapse has to move the _FrozenClock forward itself — waiting will never work.
    # slowapi keeps counters on one limiter for the whole process; clear them either
    # side so what a test sees never depends on which tests ran before it.
    limiter.reset()
    yield
    limiter.reset()

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
    assert _register(client, 0).status_code == 201  # bootstrap
    for i in range(1, 5):
        assert _register(client, i).status_code == 403  # closed, but still counted
    assert _register(client, 6).status_code == 429


def test_limits_do_not_leak_into_other_tests(client):
    payload = {"email": "ghost@example.com", "password": "Wrong123!pass"}
    for _ in range(11):
        r = client.post("/auth/login", json=payload)
        assert r.status_code == 401


def _bad_change(client, tokens):
    return client.post(
        "/auth/change-password",
        json={"current_password": "Wrong123!pass", "new_password": "Fresh123!pass"},
        headers=auth(tokens),
    )

class TestAuthenticatedRoutesAreKeyedByUser:
    def test_two_users_from_one_address_get_separate_buckets(self, client, registered_user, engineer_user, rate_limited):
        limiter.reset()  # the fixtures above already spent quota on /auth/*

        for _ in range(5):
            assert _bad_change(client, registered_user["tokens"]).status_code == 401
        assert _bad_change(client, registered_user["tokens"]).status_code == 429

        assert _bad_change(client, engineer_user).status_code == 401

def _build_probe_app():
    """A minimal app on the real key function — /auth/change-password rejects a forged
    token before the limiter runs, so it can't show the fallback paths. Built once:
    slowapi keys limits by endpoint name, so rebuilding would stack duplicates."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe")
    @limiter.limit("3/minute", key_func=user_or_address_key)
    def probe(request: Request):
        return {"ok": True}

    return TestClient(app)

_probe = _build_probe_app()

def _probe_from(address):
    return TestClient(_probe.app, client=(address, 40000))

def _rogue_token(sub):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt
    from app.config import settings as app_settings
    from app.security import get_key_id

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    now = int(time.time())
    return jwt.encode(
        {"sub": str(sub), "email": "a@b.com", "memberships": [], "is_platform_admin": False,
         "tv": 0, "leads": [], "token_type": "access", "iss": app_settings.JWT_ISSUER,
         "iat": now, "exp": now + 900},
        pem, algorithm="RS256", headers={"kid": get_key_id()},
    )

class TestUnverifiableTokensFallBackToTheAddress:
    def test_forged_bearer_tokens_share_one_bucket(self, rate_limited):
        for i in range(3):
            assert _probe.get("/probe", headers={"Authorization": f"Bearer forged-{i}"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer forged-99"}).status_code == 429

    def test_absent_and_malformed_headers_land_on_the_same_address_bucket(self, rate_limited):
        assert _probe.get("/probe").status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Basic abc"}).status_code == 200
        assert _probe.get("/probe").status_code == 429

    def test_a_real_token_is_not_dragged_into_the_fallback_bucket(self, client, registered_user, rate_limited):
        limiter.reset()
        for _ in range(3):
            assert _probe.get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 429

        assert _probe.get("/probe", headers=auth(registered_user["tokens"])).status_code == 200

    def test_the_fallback_is_the_address_and_not_one_shared_key(self, rate_limited):
        for _ in range(3):
            assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200
        assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 429

        assert _probe_from("198.51.100.2").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200

    def test_a_token_signed_by_someone_else_cannot_claim_a_users_bucket(self, client, registered_user, rate_limited):
        limiter.reset()
        user_id = registered_user["tokens"]["user"]["id"]
        for _ in range(3):
            assert _probe.get("/probe", headers={"Authorization": f"Bearer {_rogue_token(user_id)}"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": f"Bearer {_rogue_token(user_id)}"}).status_code == 429

        assert _probe.get("/probe", headers=auth(registered_user["tokens"])).status_code == 200

def _login(client, xff):
    return client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "Wrong123!pass"},
        headers={"X-Forwarded-For": xff},
    )

class TestForwardedForIsOnlyReadWhenTrusted:
    def test_untrusted_forwarded_header_buys_nothing(self, client, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        for i in range(10):
            assert _login(client, f"10.0.0.{i}").status_code == 401
        assert _login(client, "10.0.0.250").status_code == 429

    def test_trusted_forwarded_addresses_get_separate_buckets(self, client, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for _ in range(10):
            assert _login(client, "203.0.113.1").status_code == 401
        assert _login(client, "203.0.113.1").status_code == 429

        assert _login(client, "203.0.113.2").status_code == 401

    def test_only_the_entry_the_trusted_proxy_wrote_counts(self, client, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for i in range(10):
            assert _login(client, f"1.2.3.{i}, 203.0.113.9").status_code == 401
        assert _login(client, "9.9.9.9, 203.0.113.9").status_code == 429

    def test_a_second_hop_is_skipped_when_two_proxies_are_declared(self, client, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
        for _ in range(10):
            assert _login(client, "198.51.100.4, 203.0.113.9").status_code == 401
        assert _login(client, "198.51.100.4, 203.0.113.9").status_code == 429

        assert _login(client, "198.51.100.5, 203.0.113.9").status_code == 401


def _request(xff: str | None, client=("10.0.0.1", 1234)):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": client})

class TestAHeaderShorterThanTheProxyCountIsNotTrusted:
    """The mirror of a count below 1: with 3 hops and TRUSTED_PROXY_COUNT=9 the old
    `hops[-min(count, len)]` landed on hops[0] — the wholly caller-supplied end. Fewer
    hops than proxies we run means this isn't our header, so the socket address is used."""

    @pytest.fixture(autouse=True)
    def _trusted(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(rate_limit, "_short_forwarded_header_warned", False)

    def test_a_short_header_is_ignored_rather_than_read_from_its_left(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 9)
        assert rate_limit.client_address(_request("1.2.3.4, 5.6.7.8, 203.0.113.9")) == "10.0.0.1"

    def test_a_header_exactly_as_long_as_the_count_is_still_read(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 3)
        assert rate_limit.client_address(_request("1.2.3.4, 5.6.7.8, 203.0.113.9")) == "1.2.3.4"

    def test_a_short_header_cannot_mint_a_fresh_bucket_per_request(self, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 9)
        for i in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"}).status_code == 429

    def test_the_misconfiguration_is_warned_about_once_not_per_request(self, monkeypatch, caplog):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 4)
        with caplog.at_level("WARNING"):
            for _ in range(5):
                rate_limit.client_address(_request("1.2.3.4"))
        assert len([r for r in caplog.records if "TRUSTED_PROXY_COUNT" in r.getMessage()]) == 1

class TestTrustedProxyCountRefusesToDropBelowOne:
    """0 selects the leftmost X-Forwarded-For entry — the wholly caller-supplied end —
    so anyone could invent an address and get a fresh bucket. Refused when settings
    load, the way a malformed retired key refuses the boot."""

    @pytest.mark.parametrize("bad", [0, -1, -5])
    def test_settings_will_not_load_with_a_count_below_one(self, bad):
        with pytest.raises(ValidationError) as exc:
            Settings(TRUSTED_PROXY_COUNT=bad)
        assert "TRUSTED_PROXY_COUNT must be 1 or more" in str(exc.value)

    @pytest.mark.parametrize("good", [1, 2, 5])
    def test_the_valid_range_is_untouched(self, good):
        assert Settings(TRUSTED_PROXY_COUNT=good).TRUSTED_PROXY_COUNT == good

    def test_a_count_below_one_cannot_be_set_after_load_either(self):
        with pytest.raises(ValidationError):
            settings.TRUSTED_PROXY_COUNT = 0
        assert settings.TRUSTED_PROXY_COUNT >= 1

class _FakeStorage:
    def __init__(self, reachable: bool):
        self._reachable = reachable

    def check(self) -> bool:
        return self._reachable

class TestRedisBackedCountersDegradeToMemory:
    def test_storage_uri_used_when_redis_answers(self, monkeypatch):
        monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")
        monkeypatch.setattr(rate_limit, "storage_from_string", lambda uri, **kw: _FakeStorage(True))
        assert rate_limit._resolve_storage_uri() == "redis://redis:6379/0"

    def test_falls_back_to_memory_when_redis_is_unreachable(self, monkeypatch, caplog):
        monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")
        monkeypatch.setattr(rate_limit, "storage_from_string", lambda uri, **kw: _FakeStorage(False))
        with caplog.at_level("WARNING"):
            assert rate_limit._resolve_storage_uri() is None
        assert "unreachable" in caplog.text

    def test_falls_back_to_memory_when_the_probe_raises(self, monkeypatch, caplog):
        monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")

        def _boom(uri, **kw):
            raise ValueError("no driver")

        monkeypatch.setattr(rate_limit, "storage_from_string", _boom)
        with caplog.at_level("WARNING"):
            assert rate_limit._resolve_storage_uri() is None
        assert "unusable" in caplog.text

    def test_blank_redis_url_means_in_memory(self, monkeypatch):
        monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "")
        assert rate_limit._resolve_storage_uri() is None

import base64
import hashlib
import time
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt
from limits.storage import memory as limits_memory
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app import rate_limit
from app.auth import jwks_client
from pydantic import ValidationError
from app.config import Settings, settings
from app.rate_limit import limiter

CSV = b"name,age\nAlice,30\n"

class _FakeStorage:
    def __init__(self, reachable: bool):
        self._reachable = reachable

    def check(self) -> bool:
        return self._reachable

def _upload(client):
    return client.post("/datasets", files={"file": ("people.csv", CSV, "text/csv")})

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
    rate_limit.limiter.reset()
    yield
    rate_limit.limiter.reset()

@pytest.fixture
def limits_on():
    rate_limit.limiter.reset()
    rate_limit.limiter.enabled = True
    yield
    rate_limit.limiter.enabled = False
    rate_limit.limiter.reset()

def test_upload_rate_limit_fires_after_ten_per_minute(client, act_as, limits_on):
    act_as(7)
    codes = [_upload(client).status_code for _ in range(11)]
    assert codes[:10] == [201] * 10
    assert codes[10] == 429

def test_preview_rate_limit_fires_after_thirty_per_minute(client, act_as, limits_on):
    act_as(7)
    dataset_id = _upload(client).json()["id"]
    codes = [client.get(f"/datasets/{dataset_id}/preview").status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429

def test_delete_rate_limit_fires_after_thirty_per_minute(client, act_as, limits_on):
    act_as(7)
    # The 31 datasets to delete are created with limiting off, so the upload
    # limit doesn't cap the setup at 10.
    rate_limit.limiter.enabled = False
    ids = [_upload(client).json()["id"] for _ in range(31)]
    rate_limit.limiter.enabled = True
    rate_limit.limiter.reset()
    codes = [client.delete(f"/datasets/{i}").status_code for i in ids]
    assert codes[:30] == [204] * 30
    assert codes[30] == 429

def test_limits_are_off_for_the_rest_of_the_suite(client, act_as):
    act_as(7)
    assert [_upload(client).status_code for _ in range(12)] == [201] * 12

def test_storage_uri_used_when_redis_answers(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(rate_limit, "storage_from_string", lambda uri, **kw: _FakeStorage(True))
    assert rate_limit._resolve_storage_uri() == "redis://redis:6379/0"

def test_falls_back_to_memory_when_redis_is_unreachable(monkeypatch, caplog):
    monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(rate_limit, "storage_from_string", lambda uri, **kw: _FakeStorage(False))
    with caplog.at_level("WARNING"):
        assert rate_limit._resolve_storage_uri() is None
    assert "unreachable" in caplog.text

def test_falls_back_to_memory_when_the_probe_raises(monkeypatch, caplog):
    monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "redis://redis:6379/0")

    def _boom(uri, **kw):
        raise ValueError("no driver")

    monkeypatch.setattr(rate_limit, "storage_from_string", _boom)
    with caplog.at_level("WARNING"):
        assert rate_limit._resolve_storage_uri() is None
    assert "unusable" in caplog.text

def test_blank_redis_url_means_in_memory(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "")
    assert rate_limit._resolve_storage_uri() is None


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    numbers = key.public_key().public_numbers()
    b64 = lambda n: base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    kid = hashlib.sha256(pub_pem.encode()).hexdigest()[:16]
    return pem, {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": b64(numbers.n), "e": b64(numbers.e)}

# Stands in for identity: the keypair whose public half Forge's JWKS client serves.
_IDENTITY_PEM, _IDENTITY_JWK = _keypair()
# Never published, so tokens signed with it are only distinguishable by signature.
_ROGUE_PEM, _ = _keypair()

jwks_client._fetcher = lambda: {"keys": [_IDENTITY_JWK]}
jwks_client.invalidate()

def _sign(pem, user_id):
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "email": "u@x.com", "memberships": [], "leads": [],
         "is_platform_admin": False, "tv": 0, "token_type": "access",
         "iss": settings.JWT_ISSUER, "iat": now, "exp": now + 900},
        pem, algorithm="RS256", headers={"kid": _IDENTITY_JWK["kid"]},
    )

def _bearer(pem, user_id):
    return {"Authorization": f"Bearer {_sign(pem, user_id)}"}

class TestAuthenticatedRoutesAreKeyedByUser:
    def test_two_users_from_one_address_get_separate_buckets(self, client, act_as, limits_on):
        act_as(7)
        codes = [client.post("/datasets", files={"file": ("a.csv", CSV, "text/csv")}, headers=_bearer(_IDENTITY_PEM, 7)).status_code for _ in range(11)]
        assert codes[:10] == [201] * 10
        assert codes[10] == 429

        assert client.post("/datasets", files={"file": ("a.csv", CSV, "text/csv")}, headers=_bearer(_IDENTITY_PEM, 8)).status_code == 201

def _build_probe_app():
    """A minimal app on the limiter's default key function: the dataset routes' auth
    dependency rejects a bad token before the limiter runs, so they can't show the
    fallbacks. Built once — slowapi keys limits by endpoint name, so rebuilding stacks them."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe")
    @limiter.limit("3/minute")
    def probe(request: Request):
        return {"ok": True}

    return TestClient(app)

_probe = _build_probe_app()

def _probe_from(address):
    return TestClient(_probe.app, client=(address, 40000))

class TestUnverifiableTokensFallBackToTheAddress:
    def test_forged_bearer_tokens_share_one_bucket(self, limits_on):
        for i in range(3):
            assert _probe.get("/probe", headers={"Authorization": f"Bearer forged-{i}"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer forged-99"}).status_code == 429

    def test_absent_and_malformed_headers_land_on_the_same_address_bucket(self, limits_on):
        assert _probe.get("/probe").status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Basic abc"}).status_code == 200
        assert _probe.get("/probe").status_code == 429

    def test_the_fallback_is_the_address_and_not_one_shared_key(self, limits_on):
        for _ in range(3):
            assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200
        assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 429

        assert _probe_from("198.51.100.2").get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200

    def test_a_real_token_is_not_dragged_into_the_fallback_bucket(self, limits_on):
        for _ in range(3):
            assert _probe.get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer forged"}).status_code == 429

        assert _probe.get("/probe", headers=_bearer(_IDENTITY_PEM, 7)).status_code == 200

    def test_a_token_signed_by_someone_else_cannot_claim_a_users_bucket(self, limits_on):
        for _ in range(3):
            assert _probe.get("/probe", headers=_bearer(_ROGUE_PEM, 7)).status_code == 200
        assert _probe.get("/probe", headers=_bearer(_ROGUE_PEM, 7)).status_code == 429

        assert _probe.get("/probe", headers=_bearer(_IDENTITY_PEM, 7)).status_code == 200

class TestForwardedForIsOnlyReadWhenTrusted:
    def test_untrusted_forwarded_header_buys_nothing(self, limits_on, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        for i in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 200
        assert _probe.get("/probe", headers={"X-Forwarded-For": "10.0.0.250"}).status_code == 429

    def test_trusted_forwarded_addresses_get_separate_buckets(self, limits_on, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for _ in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
        assert _probe.get("/probe", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429

        assert _probe.get("/probe", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200

    def test_only_the_entry_the_trusted_proxy_wrote_counts(self, limits_on, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for i in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"}).status_code == 429

    def test_a_second_hop_is_skipped_when_two_proxies_are_declared(self, limits_on, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
        for _ in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": "198.51.100.4, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe", headers={"X-Forwarded-For": "198.51.100.4, 203.0.113.9"}).status_code == 429

        assert _probe.get("/probe", headers={"X-Forwarded-For": "198.51.100.5, 203.0.113.9"}).status_code == 200

    def test_an_empty_forwarded_header_falls_back_to_the_socket(self, limits_on, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        for _ in range(3):
            assert _probe.get("/probe", headers={"X-Forwarded-For": " , "}).status_code == 200
        assert _probe.get("/probe").status_code == 429


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

    def test_a_short_header_cannot_mint_a_fresh_bucket_per_request(self, limits_on, monkeypatch):
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

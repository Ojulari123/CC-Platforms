"""Rate limits: how much each endpoint allows, and who the allowance belongs to.

POST /reports/generate is the only endpoint that spends money (one OpenAI call per
request), so it gets a strict limit. POST /reports is a plain DB write and gets a
loose one, just so a runaway client can't hammer it.

The second half covers the KEY the counting happens under. Authenticated routes are
keyed by verified user id, so one engineer can't lock out everyone else sharing an
office address, and nobody can spend someone else's OpenAI allowance by claiming to
be them. The GitHub OAuth callback has no caller, so it stays on the address.

conftest turns the limiter off for the rest of the suite (RATE_LIMIT_ENABLED=false);
these tests switch it back on and reset its counters so they don't leak into other tests.
"""
import base64
import time
from datetime import datetime, timezone
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from crescent_core import JWKSClient
from app import rate_limit
from pydantic import ValidationError
from app.config import Settings, settings
from app.models import Commit, Repository
from app.rate_limit import address_key, limiter, user_or_address_key
from app.services import llm
from app.services.llm import LLMResult

DEPT = 1
WEEK = "2026-07-20"  # a Monday
ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])

FAKE = LLMResult(
    summary_manager="Shipped the auth refactor.",
    summary_exec="Steady progress.",
    next_week_goals="Finish token rotation.",
    model="gpt-4o-mini",
    token_count=100,
)


@pytest.fixture
def live_limiter():
    """Turn the limiter on for one test, with a clean counter either side."""
    limiter.reset()
    limiter.enabled = True
    yield limiter
    limiter.enabled = False
    limiter.reset()


@pytest.fixture
def repo_with_activity(db):
    repo = Repository(github_repo_id=1, full_name="org/alpha", owner="org", name="alpha", dept_id=DEPT)
    db.add(repo)
    db.commit()
    db.refresh(repo)
    db.add(Commit(repo_id=repo.id, sha="c1", author_user_id=10, message="work",
                  committed_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc)))
    db.commit()
    return repo


def test_generate_is_rate_limited(client, act_as, monkeypatch, live_limiter, repo_with_activity):
    monkeypatch.setattr(llm, "generate_summaries", lambda payload: FAKE)
    act_as(**ENGINEER)
    body = {"repo_id": repo_with_activity.id, "week_start": WEEK}

    codes = [client.post("/reports/generate", json=body).status_code for _ in range(11)]

    assert codes[:10] == [201] * 10, codes  # the whole hourly allowance goes through
    assert codes[10] == 429, codes          # the 11th is refused


def test_a_refused_generate_never_calls_the_llm(client, act_as, monkeypatch, live_limiter, repo_with_activity):
    """The point of the limit: the request that's over the line costs nothing."""
    calls = {"n": 0}

    def _count(payload):
        calls["n"] += 1
        return FAKE

    monkeypatch.setattr(llm, "generate_summaries", _count)
    act_as(**ENGINEER)
    body = {"repo_id": repo_with_activity.id, "week_start": WEEK}
    for _ in range(11):
        r = client.post("/reports/generate", json=body)
    assert r.status_code == 429
    assert calls["n"] == 10


def test_manual_create_has_a_looser_limit(client, act_as, live_limiter, repo_with_activity):
    act_as(**ENGINEER)
    body = {"repo_id": repo_with_activity.id, "summary_manager": "did the work"}

    codes = [client.post("/reports", json=body).status_code for _ in range(31)]

    # Well past /generate's allowance and still accepted (409 = duplicate week, which
    # still means the request was let through), then the 31st is refused.
    assert 429 not in codes[:30], codes
    assert codes[30] == 429, codes


def _b64u(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()

def _keypair(kid: str) -> tuple[str, dict]:
    """A private key PEM and the matching JWK, shaped the way identity publishes them."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numbers = key.public_key().public_numbers()
    return pem, {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
                 "n": _b64u(numbers.n), "e": _b64u(numbers.e)}

KID = "test-kid"
_REAL_PEM, _REAL_JWK = _keypair(KID)
# Same kid, different key: only a signature check tells this apart from a real token.
_ROGUE_PEM, _ = _keypair(KID)

def _token(user_id: int, pem: str = _REAL_PEM, issuer: str | None = None) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "email": f"u{user_id}@x.com", "memberships": [], "leads": [],
         "is_platform_admin": False, "tv": 0, "token_type": "access",
         "iss": issuer or settings.JWT_ISSUER, "iat": now, "exp": now + 900},
        pem, algorithm="RS256", headers={"kid": KID},
    )

def _bearer(user_id: int, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(user_id, **kw)}"}


@pytest.fixture(autouse=True)
def _identity_public_key(monkeypatch):
    """Serve the test key wherever the key function looks up identity's JWKS. The
    fetcher is injected, so nothing here touches the network."""
    monkeypatch.setattr(rate_limit, "jwks_client",
                        JWKSClient("http://identity-not-called/jwks", fetcher=lambda: {"keys": [_REAL_JWK]}))


class TestAuthenticatedRoutesAreKeyedByUser:
    def test_two_users_from_one_address_get_separate_buckets(self, client, act_as, live_limiter):
        """Same TestClient, so identical client address. User 10 burning the
        /github/sync allowance must not throttle user 11. 403 = the request was let
        through and the route said no (neither is a platform admin), which still
        spends quota."""
        act_as(**ENGINEER)

        for _ in range(5):
            assert client.post("/github/sync", headers=_bearer(10)).status_code == 403
        assert client.post("/github/sync", headers=_bearer(10)).status_code == 429

        assert client.post("/github/sync", headers=_bearer(11)).status_code == 403

    def test_one_user_cannot_spend_anothers_openai_allowance(self, client, act_as, monkeypatch, live_limiter, repo_with_activity):
        """The whole point on /reports/generate: the hourly cap is per person, and
        exhausting your own leaves everyone else's alone."""
        monkeypatch.setattr(llm, "generate_summaries", lambda payload: FAKE)
        act_as(**ENGINEER)
        body = {"repo_id": repo_with_activity.id, "week_start": WEEK}

        for _ in range(10):
            assert client.post("/reports/generate", json=body, headers=_bearer(10)).status_code in (201, 409)
        assert client.post("/reports/generate", json=body, headers=_bearer(10)).status_code == 429

        assert client.post("/reports/generate", json=body, headers=_bearer(11)).status_code in (201, 409)

    def test_a_token_signed_by_someone_else_cannot_claim_a_users_bucket(self, client, act_as, live_limiter):
        """Why the key function verifies instead of just reading `sub`: otherwise
        anyone could mint sub=<victim> and spend their quota."""
        act_as(**ENGINEER)

        for _ in range(5):
            assert client.post("/github/sync", headers=_bearer(10, pem=_ROGUE_PEM)).status_code == 403
        assert client.post("/github/sync", headers=_bearer(10, pem=_ROGUE_PEM)).status_code == 429

        assert client.post("/github/sync", headers=_bearer(10)).status_code == 403

    def test_a_token_from_the_wrong_issuer_does_not_get_a_user_bucket(self, client, act_as, live_limiter):
        act_as(**ENGINEER)
        headers = _bearer(10, issuer="somebody-elses-identity")

        for _ in range(5):
            assert client.post("/github/sync", headers=headers).status_code == 403
        assert client.post("/github/sync", headers=headers).status_code == 429

        assert client.post("/github/sync", headers=_bearer(10)).status_code == 403


def _build_probe_app():
    """A minimal app on the real key functions. The Pulse routes can't show the
    fallback paths on their own: the OAuth callback is address-keyed by design and
    the authenticated ones need a real token to be interesting.

    Built once — slowapi registers limits by endpoint name, so rebuilding it per
    test would stack duplicate limits on the same counter."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe")
    @limiter.limit("3/minute", key_func=user_or_address_key)
    def probe(request: Request):
        return {"ok": True}

    @app.get("/probe-address")
    @limiter.limit("3/minute", key_func=address_key)
    def probe_address(request: Request):
        return {"ok": True}

    return TestClient(app)

_probe = _build_probe_app()

def _probe_from(address):
    """Another caller of the same probe app, at a different address. Same app on
    purpose — a second app would register the limit twice."""
    return TestClient(_probe.app, client=(address, 40000))


class TestUnusableTokensFallBackToTheAddress:
    def test_forged_bearer_tokens_share_one_bucket(self, live_limiter):
        """A made-up token must not mint a fresh bucket per value — every one of
        these falls back to the caller's address."""
        for i in range(3):
            assert _probe.get("/probe", headers={"Authorization": f"Bearer garbage-{i}"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer garbage-99"}).status_code == 429

    def test_absent_and_malformed_headers_land_on_the_same_address_bucket(self, live_limiter):
        assert _probe.get("/probe").status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Basic abc"}).status_code == 200
        assert _probe.get("/probe").status_code == 429

    def test_a_real_token_is_not_dragged_into_the_fallback_bucket(self, live_limiter):
        """The fallback must be the address, not a key everyone shares — an
        exhausted address bucket must leave a genuine caller alone."""
        for _ in range(3):
            assert _probe.get("/probe", headers={"Authorization": "Bearer garbage"}).status_code == 200
        assert _probe.get("/probe", headers={"Authorization": "Bearer garbage"}).status_code == 429

        assert _probe.get("/probe", headers=_bearer(10)).status_code == 200

    def test_the_fallback_is_the_address_and_not_one_shared_key(self, live_limiter):
        """Two callers with unusable tokens must still be told apart. A constant
        fallback key would pass the tests above and quietly let one stranger
        throttle every other."""
        for _ in range(3):
            assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer garbage"}).status_code == 200
        assert _probe_from("198.51.100.1").get("/probe", headers={"Authorization": "Bearer garbage"}).status_code == 429

        assert _probe_from("198.51.100.2").get("/probe", headers={"Authorization": "Bearer garbage"}).status_code == 200

    def test_an_unreachable_jwks_falls_back_instead_of_erroring(self, live_limiter, monkeypatch):
        """Identity's key endpoint being down must not turn key derivation into the
        thing that breaks the request — the auth dependency is where that gets
        reported."""
        import httpx

        def _boom():
            raise httpx.ConnectError("jwks unreachable")

        monkeypatch.setattr(rate_limit, "jwks_client", JWKSClient("http://identity-not-called/jwks", fetcher=_boom))
        for _ in range(3):
            assert _probe.get("/probe", headers=_bearer(10)).status_code == 200
        assert _probe.get("/probe", headers=_bearer(10)).status_code == 429
        # Fell back to the address, so a caller elsewhere is untouched.
        assert _probe_from("198.51.100.7").get("/probe", headers=_bearer(11)).status_code == 200


class TestForwardedForIsOnlyReadWhenTrusted:
    def test_untrusted_forwarded_header_buys_nothing(self, live_limiter, monkeypatch):
        """The default. A new X-Forwarded-For per request must not reset the count,
        or the header becomes a bypass for every address limit."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        for i in range(3):
            assert _probe.get("/probe-address", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 200
        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "10.0.0.250"}).status_code == 429

    def test_trusted_forwarded_addresses_get_separate_buckets(self, live_limiter, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for _ in range(3):
            assert _probe.get("/probe-address", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429

        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200

    def test_only_the_entry_the_trusted_proxy_wrote_counts(self, live_limiter, monkeypatch):
        """With one proxy in front, the rightmost entry is the one it appended.
        Entries to the left came from the caller, so varying them must not shake the
        limit off."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        for i in range(3):
            assert _probe.get("/probe-address", headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"}).status_code == 429

    def test_a_second_hop_is_skipped_when_two_proxies_are_declared(self, live_limiter, monkeypatch):
        """Two proxies: the rightmost entry is our own inner proxy, so the caller is
        one further left."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
        for _ in range(3):
            assert _probe.get("/probe-address", headers={"X-Forwarded-For": "198.51.100.4, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "198.51.100.4, 203.0.113.9"}).status_code == 429

        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "198.51.100.5, 203.0.113.9"}).status_code == 200


def test_the_oauth_callback_stays_on_the_address(client, live_limiter):
    """GitHub redirects a browser here with no Authorization header at all, so there
    is no user to key on. 303 = bad state bounced back to the frontend, i.e. the
    request reached the route."""
    params = {"code": "x", "state": "not-a-real-state"}
    codes = [client.get("/github/oauth/callback", params=params, follow_redirects=False).status_code for _ in range(21)]
    assert codes[:20] == [303] * 20, codes
    assert codes[20] == 429, codes


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

    def test_a_short_header_cannot_mint_a_fresh_bucket_per_request(self, live_limiter, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 9)
        for i in range(3):
            assert _probe.get("/probe-address", headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.9"}).status_code == 200
        assert _probe.get("/probe-address", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"}).status_code == 429

    def test_the_misconfiguration_is_warned_about_once_not_per_request(self, monkeypatch, caplog):
        """A caller chooses when this fires, so a warning per request would be a
        log-flooding lever. One per process is enough to spot a real misconfiguration."""
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

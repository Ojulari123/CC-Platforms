"""The Redis side of revocation. Tests pin REDIS_URL to "" (conftest), so the module is
a no-op unless a test points it somewhere, which is also the production behaviour when
Redis is not configured."""
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from app import revocations
from app.config import settings
from tests.conftest import auth

class FakeRedis:

    def __init__(self, fail: bool = False):
        self.written: list[tuple[str, str, int]] = []
        self.fail = fail

    def set(self, key, value, ex=None):
        if self.fail:
            raise RedisConnectionError("redis is down")
        self.written.append((key, value, ex))

@pytest.fixture
def published(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(revocations, "_redis", lambda: fake)
    return fake

def _login(client, registered_user) -> dict:
    r = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
    assert r.status_code == 200, r.text
    return r.json()

class TestClientResolution:
    def test_no_redis_url_means_no_client_and_no_writes(self, monkeypatch):
        monkeypatch.setattr(settings, "REDIS_URL", "")
        revocations.reset_client()
        assert revocations._redis() is None
        revocations.publish_session_revoked("abc")  # must not raise
        revocations.reset_client()

    def test_an_unusable_url_is_logged_not_raised(self, monkeypatch):
        monkeypatch.setattr(settings, "REDIS_URL", "not-a-redis-url")
        revocations.reset_client()
        assert revocations._redis() is None
        revocations.reset_client()

    def test_a_usable_url_builds_a_client_once(self, monkeypatch):
        monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        revocations.reset_client()
        first = revocations._redis()
        assert first is not None
        assert revocations._redis() is first  # from_url is not called again
        revocations.reset_client()

    def test_a_dead_redis_does_not_break_the_caller(self, monkeypatch):
        monkeypatch.setattr(revocations, "_redis", lambda: FakeRedis(fail=True))
        revocations.publish_user_revoked(7, 3)  # swallowed: the DB write is what counts

class TestTTL:
    def test_it_outlives_an_access_token_by_the_skew_margin(self):
        expected = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + revocations.CLOCK_SKEW_SECONDS
        assert revocations.ttl_seconds() == expected

class TestWhatGetsPublished:
    def test_per_device_sign_out_publishes_the_session_only(self, client, registered_user, published):
        tokens = _login(client, registered_user)
        assert client.delete("/me/sessions/current", headers=auth(tokens)).status_code == 204

        assert len(published.written) == 1
        key, value, ttl = published.written[0]
        assert key.startswith(revocations.SESSION_KEY_PREFIX)
        assert value == "1"
        assert ttl == revocations.ttl_seconds()
        # no user-wide marker: this deliberately does not touch the account
        assert not any(k.startswith(revocations.USER_KEY_PREFIX) for k, _, _ in published.written)

    def test_the_published_session_id_is_the_sid_claim(self, client, registered_user, published):
        from app.security.jwt import decode_access_token

        tokens = _login(client, registered_user)
        client.delete("/me/sessions/current", headers=auth(tokens))
        expected = decode_access_token(tokens["access_token"]).session_id
        assert published.written[0][0] == f"{revocations.SESSION_KEY_PREFIX}{expected}"

    def test_logout_all_publishes_the_new_token_version(self, client, registered_user, published):
        tokens = _login(client, registered_user)
        assert client.post("/auth/logout-all", headers=auth(tokens)).status_code == 204

        user_id = decode = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]}).json()["user"]["id"]
        key, value, ttl = published.written[0]
        assert key == f"{revocations.USER_KEY_PREFIX}{user_id}"
        assert int(value) >= 1
        assert ttl == revocations.ttl_seconds()

    def test_password_change_publishes_a_user_marker(self, client, registered_user, published):
        r = client.post(
            "/auth/change-password",
            json={"current_password": registered_user["password"], "new_password": "Brand1!newpass"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 200
        assert [k.split(":")[1] for k, _, _ in published.written] == ["user"]

    def test_refresh_token_reuse_publishes_a_user_marker(self, client, registered_user, published):
        first = client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})
        assert first.status_code == 200
        again = client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})
        assert again.status_code == 401
        assert [k.split(":")[1] for k, _, _ in published.written] == ["user"]

    def test_plain_logout_publishes_that_session(self, client, registered_user, published):
        from app.security.jwt import decode_access_token

        tokens = _login(client, registered_user)
        assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        expected = decode_access_token(tokens["access_token"]).session_id
        assert published.written == [(f"{revocations.SESSION_KEY_PREFIX}{expected}", "1", revocations.ttl_seconds())]

    def test_logging_out_an_unknown_token_publishes_nothing(self, client, registered_user, published):
        assert client.post("/auth/logout", json={"refresh_token": "never-existed"}).status_code == 204
        assert published.written == []

    def test_a_failed_lookup_publishes_nothing(self, client, registered_user, published):
        assert client.delete("/me/sessions/deadbeef", headers=auth(registered_user["tokens"])).status_code == 404
        assert published.written == []

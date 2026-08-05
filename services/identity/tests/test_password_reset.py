"""
The response must not reveal whether an address has an account, and completing a reset must kill
every existing session."""
import pytest

from tests.conftest import auth


@pytest.fixture
def sent_resets(monkeypatch):
    """Capture reset emails and pretend email is configured (test env has blank
    Brevo creds). Each entry carries the raw token"""
    from app.services import email as email_service

    captured = []
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(
        email_service, "send_password_reset",
        lambda to, raw_token: captured.append({"to": to, "raw_token": raw_token}),
    )
    return captured

def _forgot(client, email):
    return client.post("/auth/forgot-password", json={"email": email})

def _reset(client, token, new_password="NewPass123!"):
    return client.post("/auth/reset-password", json={"token": token, "new_password": new_password})

class TestForgotPassword:
    def test_known_user_gets_a_link(self, client, registered_user, sent_resets):
        r = _forgot(client, registered_user["email"])
        assert r.status_code == 204
        assert len(sent_resets) == 1
        assert sent_resets[0]["to"] == registered_user["email"]
        assert sent_resets[0]["raw_token"]

    def test_unknown_email_looks_identical_and_sends_nothing(self, client, registered_user, sent_resets):
        r = _forgot(client, "nobody@example.com")
        assert r.status_code == 204  # same as a real address — no enumeration
        assert sent_resets == []

    def test_503_only_when_email_is_misconfigured(self, client, registered_user):
        # is_configured() reads the blank test creds.
        # The 503 is about the server, not the address — it can't be used to probe.
        assert _forgot(client, registered_user["email"]).status_code == 503
        assert _forgot(client, "nobody@example.com").status_code == 503

    def test_requesting_again_invalidates_the_previous_link(self, client, registered_user, sent_resets):
        _forgot(client, registered_user["email"])
        first = sent_resets[-1]["raw_token"]
        _forgot(client, registered_user["email"])
        second = sent_resets[-1]["raw_token"]
        assert first != second
        assert _reset(client, first).status_code == 400  # superseded
        assert _reset(client, second).status_code == 204

class TestResetPassword:
    def test_reset_sets_the_new_password(self, client, registered_user, sent_resets):
        _forgot(client, registered_user["email"])
        assert _reset(client, sent_resets[-1]["raw_token"]).status_code == 204

        old = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
        assert old.status_code == 401
        new = client.post("/auth/login", json={"email": registered_user["email"], "password": "NewPass123!"})
        assert new.status_code == 200

    def test_reset_logs_the_account_out_everywhere(self, client, registered_user, sent_resets):
        old_tokens = registered_user["tokens"]
        _forgot(client, registered_user["email"])
        assert _reset(client, sent_resets[-1]["raw_token"]).status_code == 204

        # Old access token: rejected because token_version was bumped.
        assert client.get("/me", headers=auth(old_tokens)).status_code == 401
        # Old refresh token: revoked.
        assert client.post("/auth/refresh", json={"refresh_token": old_tokens["refresh_token"]}).status_code == 401

    def test_a_used_token_cannot_be_reused(self, client, registered_user, sent_resets):
        _forgot(client, registered_user["email"])
        token = sent_resets[-1]["raw_token"]
        assert _reset(client, token).status_code == 204
        assert _reset(client, token).status_code == 400

    def test_garbage_token_is_rejected(self, client, registered_user, sent_resets):
        assert _reset(client, "not-a-real-token").status_code == 400

    def test_expired_token_is_rejected(self, client, registered_user, sent_resets, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "PASSWORD_RESET_EXPIRE_MINUTES", -1)
        _forgot(client, registered_user["email"])
        assert _reset(client, sent_resets[-1]["raw_token"]).status_code == 400

    def test_weak_new_password_is_rejected(self, client, registered_user, sent_resets):
        _forgot(client, registered_user["email"])
        # 8+ chars so it clears the schema, but no uppercase/special → validate_password 400.
        assert _reset(client, sent_resets[-1]["raw_token"], new_password="lowercase1").status_code == 400

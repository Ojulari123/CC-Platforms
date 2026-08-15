import pytest
from sqlalchemy import select

from app.models import EmailChangeToken, User
from tests.conftest import auth

NEW_EMAIL = "alice.new@example.com"


@pytest.fixture
def sent_email_changes(monkeypatch):
    from app.services import email as email_service

    captured = {"verifications": [], "notices": []}
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(
        email_service, "send_email_change_verification",
        lambda to, raw_token: captured["verifications"].append({"to": to, "raw_token": raw_token}),
    )
    monkeypatch.setattr(
        email_service, "send_email_change_notice",
        lambda to, new_email: captured["notices"].append({"to": to, "new_email": new_email}),
    )
    return captured

def _request(client, tokens, new_email=NEW_EMAIL, password="Test123!password"):
    return client.post(
        "/auth/change-email",
        json={"new_email": new_email, "current_password": password},
        headers=auth(tokens),
    )

def _confirm(client, token):
    return client.post("/auth/confirm-email-change", json={"token": token})

class TestRequestEmailChange:
    def test_happy_path_swaps_the_address_and_ends_every_session(self, client, registered_user, sent_email_changes):
        tokens = registered_user["tokens"]
        assert _request(client, tokens).status_code == 204

        # link goes to the NEW address, warning to the old one
        assert [m["to"] for m in sent_email_changes["verifications"]] == [NEW_EMAIL]
        assert sent_email_changes["notices"] == [{"to": registered_user["email"], "new_email": NEW_EMAIL}]

        # nothing has moved yet
        assert client.get("/me", headers=auth(tokens)).json()["email"] == registered_user["email"]

        assert _confirm(client, sent_email_changes["verifications"][-1]["raw_token"]).status_code == 204

        old = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
        assert old.status_code == 401
        fresh = client.post("/auth/login", json={"email": NEW_EMAIL, "password": registered_user["password"]})
        assert fresh.status_code == 200
        assert fresh.json()["user"]["email"] == NEW_EMAIL
        assert fresh.json()["user"]["email_verified"] is True

        # token_version bumped, so the access token dies with the refresh family
        assert client.get("/me", headers=auth(tokens)).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401

    def test_wrong_current_password_is_refused(self, client, registered_user, sent_email_changes):
        r = _request(client, registered_user["tokens"], password="NotMyPassword1!")
        assert r.status_code == 401
        assert r.json()["detail"] == "Current password is incorrect"
        assert sent_email_changes["verifications"] == []
        assert sent_email_changes["notices"] == []

    def test_unauthenticated_request_is_401(self, client, registered_user, sent_email_changes):
        r = client.post("/auth/change-email", json={"new_email": NEW_EMAIL, "current_password": registered_user["password"]})
        assert r.status_code == 401
        assert sent_email_changes["verifications"] == []

    def test_no_token_material_in_the_response(self, client, registered_user, sent_email_changes):
        r = _request(client, registered_user["tokens"])
        assert r.status_code == 204
        assert r.content == b""
        raw_token = sent_email_changes["verifications"][-1]["raw_token"]

        confirm = _confirm(client, raw_token)
        assert confirm.status_code == 204
        assert confirm.content == b""
        assert raw_token not in r.text
        assert raw_token not in confirm.text

    def test_address_already_in_use_is_refused_outright_and_sends_nothing(self, client, registered_user, engineer_user, sent_email_changes):
        # Was a silent 204 to avoid an enumeration oracle. It is a poor oracle — the
        # endpoint is authenticated, password-re-authed and rate limited — and the price
        # was telling someone to check an inbox no mail would ever arrive in.
        r = _request(client, registered_user["tokens"], new_email="eng@example.com")
        assert r.status_code == 409
        assert r.json()["detail"] == "An account with that email already exists"
        assert sent_email_changes["verifications"] == []
        assert sent_email_changes["notices"] == []

    def test_a_taken_address_is_refused_case_insensitively(self, client, registered_user, engineer_user, sent_email_changes):
        assert _request(client, registered_user["tokens"], new_email="  ENG@Example.com ").status_code == 409
        assert sent_email_changes["verifications"] == []

    def test_a_taken_address_still_cancels_a_pending_link(self, client, registered_user, engineer_user, sent_email_changes):
        # The refusal comes after pending links are cleared, so asking for an address
        # that turns out to be taken does not leave the earlier request live.
        assert _request(client, registered_user["tokens"]).status_code == 204
        pending = sent_email_changes["verifications"][-1]["raw_token"]
        assert _request(client, registered_user["tokens"], new_email="eng@example.com").status_code == 409
        assert _confirm(client, pending).status_code == 400

    def test_the_refusal_needs_the_password_first(self, client, registered_user, engineer_user, sent_email_changes):
        # So it cannot be used as a "does this address exist" probe from a stolen session.
        r = _request(client, registered_user["tokens"], new_email="eng@example.com", password="NotMyPassword1!")
        assert r.status_code == 401
        assert r.json()["detail"] == "Current password is incorrect"

    def test_own_address_is_rejected_outright(self, client, registered_user, sent_email_changes):
        r = _request(client, registered_user["tokens"], new_email=registered_user["email"])
        assert r.status_code == 400
        assert r.json()["detail"] == "That's already the email on this account"

    def test_address_is_normalised_before_use(self, client, registered_user, sent_email_changes):
        assert _request(client, registered_user["tokens"], new_email="  Alice.NEW@Example.com  ").status_code == 204
        assert sent_email_changes["verifications"][-1]["to"] == NEW_EMAIL
        assert _confirm(client, sent_email_changes["verifications"][-1]["raw_token"]).status_code == 204
        assert client.post("/auth/login", json={"email": NEW_EMAIL, "password": registered_user["password"]}).status_code == 200

    def test_503_when_email_is_not_configured(self, client, registered_user):
        # is_configured() reads the blank test creds, and the check runs before the
        # password is even looked at, so it says nothing about the account.
        assert _request(client, registered_user["tokens"]).status_code == 503

    def test_a_failed_send_does_not_surface_to_the_caller(self, client, registered_user, monkeypatch):
        from app.services import email as email_service

        monkeypatch.setattr(email_service, "is_configured", lambda: True)
        def boom(**kwargs):
            raise email_service.EmailSendError("provider down")
        monkeypatch.setattr(email_service, "send_email_change_verification", boom)
        monkeypatch.setattr(email_service, "send_email_change_notice", boom)
        assert _request(client, registered_user["tokens"]).status_code == 204

class TestConfirmEmailChange:
    def test_a_used_token_cannot_be_reused(self, client, registered_user, sent_email_changes):
        _request(client, registered_user["tokens"])
        token = sent_email_changes["verifications"][-1]["raw_token"]
        assert _confirm(client, token).status_code == 204
        assert _confirm(client, token).status_code == 400

    def test_requesting_again_invalidates_the_previous_link(self, client, registered_user, sent_email_changes):
        _request(client, registered_user["tokens"])
        first = sent_email_changes["verifications"][-1]["raw_token"]
        _request(client, registered_user["tokens"], new_email="alice.other@example.com")
        second = sent_email_changes["verifications"][-1]["raw_token"]
        assert first != second
        assert _confirm(client, first).status_code == 400  # superseded
        assert _confirm(client, second).status_code == 204
        assert client.post("/auth/login", json={"email": "alice.other@example.com", "password": registered_user["password"]}).status_code == 200

    def test_expired_token_is_rejected(self, client, registered_user, sent_email_changes, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "EMAIL_CHANGE_EXPIRE_MINUTES", -1)
        _request(client, registered_user["tokens"])
        assert _confirm(client, sent_email_changes["verifications"][-1]["raw_token"]).status_code == 400

    def test_garbage_token_is_rejected(self, client, registered_user):
        assert _confirm(client, "not-a-real-token").status_code == 400

    def test_changing_the_password_kills_a_pending_link(self, client, registered_user, sent_email_changes):
        tokens = registered_user["tokens"]
        _request(client, tokens)
        pending = sent_email_changes["verifications"][-1]["raw_token"]
        # This is how someone shuts down a request they didn't make.
        r = client.post(
            "/auth/change-password",
            json={"current_password": registered_user["password"], "new_password": "Brand1!newpass"},
            headers=auth(tokens),
        )
        assert r.status_code == 200
        assert _confirm(client, pending).status_code == 400
        assert client.post("/auth/login", json={"email": NEW_EMAIL, "password": "Brand1!newpass"}).status_code == 401

    def test_signing_out_everywhere_kills_a_pending_link(self, client, registered_user, sent_email_changes):
        tokens = registered_user["tokens"]
        _request(client, tokens)
        pending = sent_email_changes["verifications"][-1]["raw_token"]
        assert client.post("/auth/logout-all", headers=auth(tokens)).status_code == 204
        assert _confirm(client, pending).status_code == 400

    def test_address_claimed_before_confirming_is_409(self, client, registered_user, invite_user, sent_email_changes):
        _request(client, registered_user["tokens"])
        pending = sent_email_changes["verifications"][-1]["raw_token"]
        # Someone else takes the address in the meantime.
        invite_user(registered_user["tokens"], registered_user["dept_id"], NEW_EMAIL)
        r = _confirm(client, pending)
        assert r.status_code == 409
        assert r.json()["detail"] == "That email address is no longer available"
        assert _confirm(client, pending).status_code == 400  # burnt on the way out

    def test_deactivated_account_cannot_confirm(self, client, registered_user, engineer_user, sent_email_changes, db_session):
        r = client.post(
            "/auth/change-email",
            json={"new_email": NEW_EMAIL, "current_password": "Test123!password"},
            headers=auth(engineer_user),
        )
        assert r.status_code == 204
        pending = sent_email_changes["verifications"][-1]["raw_token"]
        user = db_session.scalar(select(User).where(User.email == "eng@example.com"))
        user.is_active = False
        db_session.commit()
        assert _confirm(client, pending).status_code == 400

    def test_the_raw_token_is_never_stored(self, client, registered_user, sent_email_changes, db_session):
        _request(client, registered_user["tokens"])
        raw_token = sent_email_changes["verifications"][-1]["raw_token"]
        row = db_session.scalar(select(EmailChangeToken))
        assert row.token_hash != raw_token
        assert len(row.token_hash) == 64
        assert row.new_email == NEW_EMAIL

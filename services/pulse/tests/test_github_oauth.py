import json
import time
from urllib.parse import parse_qs, urlparse
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from app import crypto
from app.config import settings
from app.models import GitHubAccount
from app.routes import github as github_routes
from app.services import github_oauth

ADA = dict(user_id=42, memberships=[{"dept_id": 1, "team_id": 5, "role": "engineer"}])
BEN = dict(user_id=99, memberships=[{"dept_id": 1, "team_id": 5, "role": "engineer"}])

FRONTEND = "http://localhost:3000"

@pytest.fixture
def fake_github(monkeypatch):
    state = {"login": "ada-gh", "id": 123456}

    def set_user(login, gid):
        state["login"], state["id"] = login, gid

    monkeypatch.setattr(github_oauth, "exchange_code_for_token", lambda code: f"gho_token_for_{code}")
    monkeypatch.setattr(github_oauth, "fetch_github_user", lambda token: {"login": state["login"], "id": state["id"]})
    return set_user

def _callback(client, uid, code="abc", **extra_params):
    state = crypto.sign_state({"uid": uid, "nonce": "n"})
    return _raw_callback(client, code=code, state=state, **extra_params)

def _raw_callback(client, **params):
    return client.get("/github/oauth/callback", params=params, follow_redirects=False)

def _outcome(response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith(f"{FRONTEND}/?"), location
    return parse_qs(urlparse(location).query)["github"][0]

class TestConnect:
    def test_connect_returns_a_github_authorize_url(self, client, act_as):
        act_as(**ADA)
        r = client.get("/github/connect")
        assert r.status_code == 200
        url = r.json()["authorize_url"]
        assert url.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=test-client-id" in url
        assert "state=" in url and "scope=read" in url

    def test_connect_requires_a_login(self, client):
        assert client.get("/github/connect").status_code == 401

class TestCallback:
    def test_callback_links_the_account_and_encrypts_the_token(self, client, act_as, db, fake_github):
        assert _outcome(_callback(client, uid=42)) == "connected"

        account = db.query(GitHubAccount).one()
        assert account.user_id == 42
        assert account.github_login == "ada-gh"
        assert account.access_token_encrypted != "gho_token_for_abc"
        assert crypto.decrypt(account.access_token_encrypted) == "gho_token_for_abc"

    def test_reconnecting_updates_in_place(self, client, act_as, db, fake_github):
        _callback(client, uid=42)
        _callback(client, uid=42)
        assert db.query(GitHubAccount).count() == 1

    def test_bad_state_is_rejected(self, client, db, fake_github):
        r = _raw_callback(client, code="abc", state="not-a-real-state")
        assert _outcome(r) == "expired"
        assert db.query(GitHubAccount).count() == 0

    def test_a_tampered_state_is_rejected(self, client, db, fake_github):
        good = crypto.sign_state({"uid": 42, "nonce": "n"})
        forged = good[:-4] + ("aaaa" if not good.endswith("aaaa") else "bbbb")
        assert _outcome(_raw_callback(client, code="abc", state=forged)) == "expired"
        assert db.query(GitHubAccount).count() == 0

    def test_an_expired_state_is_rejected(self, client, db, fake_github):
        signed_at = int(time.time()) - github_oauth.STATE_MAX_AGE_SECONDS - 60
        stale = Fernet(settings.GITHUB_TOKEN_ENC_KEY.encode()).encrypt_at_time(
            json.dumps({"uid": 42, "nonce": "n"}).encode(), signed_at
        ).decode()
        assert _outcome(_raw_callback(client, code="abc", state=stale)) == "expired"
        assert db.query(GitHubAccount).count() == 0

    def test_declining_on_github_lands_back_in_pulse(self, client, db, fake_github):
        state = crypto.sign_state({"uid": 42, "nonce": "n"})
        r = _raw_callback(client, error="access_denied", error_description="The user has denied your application access.", state=state)
        assert _outcome(r) == "denied"
        assert db.query(GitHubAccount).count() == 0

    def test_any_other_github_error_lands_back_in_pulse(self, client, fake_github):
        assert _outcome(_raw_callback(client, error="application_suspended", state="whatever")) == "failed"

    def test_a_callback_with_no_code_lands_back_in_pulse(self, client, fake_github):
        state = crypto.sign_state({"uid": 42, "nonce": "n"})
        assert _outcome(_raw_callback(client, state=state)) == "failed"

    def test_a_callback_with_no_state_lands_back_in_pulse(self, client, db, fake_github):
        assert _outcome(_raw_callback(client, code="abc")) == "failed"
        assert db.query(GitHubAccount).count() == 0

    def test_a_rejected_token_exchange_lands_back_in_pulse(self, client, db, monkeypatch):
        def refuse(code):
            raise HTTPException(status_code=502, detail="GitHub rejected the authorization: bad_verification_code")

        monkeypatch.setattr(github_oauth, "exchange_code_for_token", refuse)
        assert _outcome(_callback(client, uid=42)) == "failed"
        assert db.query(GitHubAccount).count() == 0

    def test_github_being_unreachable_lands_back_in_pulse(self, client, db, monkeypatch):
        def boom(code):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(github_oauth, "exchange_code_for_token", boom)
        assert _outcome(_callback(client, uid=42)) == "failed"
        assert db.query(GitHubAccount).count() == 0

    def test_oauth_not_configured_lands_back_in_pulse(self, client, monkeypatch, fake_github):
        monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "")
        assert _outcome(_callback(client, uid=42)) == "not_configured"

    def test_one_github_account_cannot_link_to_two_users(self, client, db, fake_github):
        fake_github("shared-gh", 555)
        assert _outcome(_callback(client, uid=42)) == "connected"
        assert _outcome(_callback(client, uid=99)) == "already_linked"

    def test_the_landing_page_comes_from_configuration(self, client, monkeypatch, fake_github):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://pulse.cyphercrescent.test/")
        r = _callback(client, uid=42)
        assert r.headers["location"] == "https://pulse.cyphercrescent.test/?github=connected"

class TestCallbackRedirectCannotBeSteered:

    def _assert_lands_on_the_frontend(self, response):
        location = response.headers["location"]
        assert urlparse(location).netloc == urlparse(FRONTEND).netloc, location
        assert "evil" not in location, location
        return location

    def test_redirect_params_in_the_query_string_are_ignored(self, client, fake_github):
        r = _callback(
            client,
            uid=42,
            redirect_uri="https://evil.example/steal",
            next="https://evil.example/steal",
            return_to="//evil.example",
            state_url="https://evil.example",
        )
        assert self._assert_lands_on_the_frontend(r).endswith("?github=connected")

    def test_a_forged_state_does_not_redirect_anywhere_it_names(self, client, db, fake_github):
        forged = Fernet(Fernet.generate_key()).encrypt(
            json.dumps({"uid": 42, "return_to": "https://evil.example"}).encode()
        ).decode()
        r = _raw_callback(client, code="abc", state=forged)
        self._assert_lands_on_the_frontend(r)
        assert db.query(GitHubAccount).count() == 0

    def test_a_valid_state_carrying_a_redirect_does_not_move_the_target(self, client, fake_github):
        state = crypto.sign_state({"uid": 42, "nonce": "n", "return_to": "https://evil.example"})
        r = _raw_callback(client, code="abc", state=state)
        assert self._assert_lands_on_the_frontend(r).endswith("?github=connected")

    def test_host_headers_do_not_move_the_target(self, client, fake_github):
        state = crypto.sign_state({"uid": 42, "nonce": "n"})
        r = client.get(
            "/github/oauth/callback",
            params={"code": "abc", "state": state},
            headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http"},
            follow_redirects=False,
        )
        self._assert_lands_on_the_frontend(r)

    def test_an_unlisted_result_code_cannot_reach_the_url(self):
        r = github_routes._back_to_pulse("https://evil.example/?x=")
        assert r.headers["location"] == f"{FRONTEND}/?github=failed"

    def test_the_result_code_is_never_taken_from_the_caller(self, client, fake_github):
        r = _callback(client, uid=42, github="connected%26x%3Dhttps://evil.example")
        location = self._assert_lands_on_the_frontend(r)
        assert parse_qs(urlparse(location).query) == {"github": ["connected"]}

class TestViewAndDisconnect:
    def test_account_404_when_not_connected(self, client, act_as):
        act_as(**ADA)
        assert client.get("/github/account").status_code == 404

    def test_view_and_disconnect(self, client, act_as, fake_github):
        _callback(client, uid=42)
        act_as(**ADA)
        assert client.get("/github/account").json()["github_login"] == "ada-gh"
        assert client.delete("/github/account").status_code == 204
        assert client.get("/github/account").status_code == 404

    def test_disconnect_requires_a_login(self, client):
        assert client.delete("/github/account").status_code == 401

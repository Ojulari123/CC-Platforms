"""Slice 3: connect a GitHub account (OAuth). GitHub itself is monkeypatched —
the token exchange and user lookup are replaced, so no real network is touched.
What's exercised: the authorize URL, the callback upsert, token encryption at
rest, the signed-state guard, and connect/view/disconnect auth."""
import pytest
from app import crypto
from app.models import GitHubAccount
from app.services import github_oauth

ADA = dict(user_id=42, memberships=[{"dept_id": 1, "team_id": 5, "role": "engineer"}])
BEN = dict(user_id=99, memberships=[{"dept_id": 1, "team_id": 5, "role": "engineer"}])


@pytest.fixture
def fake_github(monkeypatch):
    """Stand in for GitHub: any code becomes a token, and the token maps to a
    fixed GitHub user. Tests can override the user via `set_user`."""
    state = {"login": "ada-gh", "id": 123456}

    def set_user(login, gid):
        state["login"], state["id"] = login, gid

    monkeypatch.setattr(github_oauth, "exchange_code_for_token", lambda code: f"gho_token_for_{code}")
    monkeypatch.setattr(github_oauth, "fetch_github_user", lambda token: {"login": state["login"], "id": state["id"]})
    return set_user


def _callback(client, uid, code="abc"):
    state = crypto.sign_state({"uid": uid, "nonce": "n"})
    return client.get(f"/github/oauth/callback?code={code}&state={state}")


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
        r = _callback(client, uid=42)
        assert r.status_code == 200
        assert "ada-gh" in r.text

        account = db.query(GitHubAccount).one()
        assert account.user_id == 42
        assert account.github_login == "ada-gh"
        # stored token is NOT plaintext, but decrypts back to the real one
        assert account.access_token_encrypted != "gho_token_for_abc"
        assert crypto.decrypt(account.access_token_encrypted) == "gho_token_for_abc"

    def test_reconnecting_updates_in_place(self, client, act_as, db, fake_github):
        _callback(client, uid=42)
        _callback(client, uid=42)  # same user again
        assert db.query(GitHubAccount).count() == 1

    def test_bad_state_is_rejected(self, client, fake_github):
        r = client.get("/github/oauth/callback?code=abc&state=not-a-real-state")
        assert r.status_code == 400

    def test_one_github_account_cannot_link_to_two_users(self, client, db, fake_github):
        fake_github("shared-gh", 555)
        assert _callback(client, uid=42).status_code == 200
        assert _callback(client, uid=99).status_code == 409  # same github id, different user


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

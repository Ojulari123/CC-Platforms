import pytest
from sqlalchemy import select
from app.models import ServiceClient
from app.security.jwt import create_access_token, create_service_token
from app.services.service_clients import seed_service_client

CLIENT_ID = "pulse"
CLIENT_SECRET = "s3cret-known-only-to-tests"
SCOPE = "users:read:email"

def _seed(db, secret=CLIENT_SECRET, scopes=SCOPE, active=True):
    client = seed_service_client(db, client_id=CLIENT_ID, secret=secret, scopes=scopes)
    if not active:
        client.is_active = False
        db.commit()
    return client

def _get_service_token(client, secret=CLIENT_SECRET):
    r = client.post("/oauth/token", json={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": secret,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestClientCredentialsToken:
    """OAuth2 client-credentials mint at POST /oauth/token."""

    def test_valid_credentials_returns_token(self, client, db_session):
        _seed(db_session)
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 10 * 60
        assert body["access_token"]

    def test_wrong_secret_is_401(self, client, db_session):
        _seed(db_session)
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": "wrong",
        })
        assert r.status_code == 401

    def test_unknown_client_is_401(self, client, db_session):
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": "ghost",
            "client_secret": "whatever",
        })
        assert r.status_code == 401

    def test_inactive_client_is_401(self, client, db_session):
        _seed(db_session, active=False)
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        })
        assert r.status_code == 401

    def test_bad_grant_type_is_400(self, client, db_session):
        _seed(db_session)
        r = client.post("/oauth/token", json={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        })
        assert r.status_code == 400


class TestEmailLookup:
    """POST /internal/users/emails — scope-gated service-to-service lookup."""

    def _users(self, client, registered_user, invite_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        eng = invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")
        eng_me = client.get("/me", headers={"Authorization": f"Bearer {eng['access_token']}"}).json()
        return alice, eng_me

    def test_returns_id_to_email_map(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        _seed(db_session)
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": [alice["id"], eng["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        got = {u["user_id"]: u["email"] for u in r.json()["users"]}
        assert got == {alice["id"]: alice["email"], eng["id"]: eng["email"]}

    def test_unknown_ids_are_omitted(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session)
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": [alice["id"], 999999]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        ids = [u["user_id"] for u in r.json()["users"]]
        assert ids == [alice["id"]]

    def test_missing_scope_is_403(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes="something:else")
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": [alice["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_user_access_token_is_rejected(self, client, db_session, registered_user):
        """A normal user JWT must NOT open a service endpoint — wrong token_type."""
        user_token = registered_user["tokens"]["access_token"]
        r = client.post("/internal/users/emails",
                        json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code in (401, 403)
        assert r.status_code == 401  # decode_service_token rejects token_type before scope check

    def test_malformed_token_is_401(self, client, db_session):
        r = client.post("/internal/users/emails",
                        json={"user_ids": [1]},
                        headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401

    def test_expired_token_is_401(self, client, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "SERVICE_TOKEN_EXPIRE_MINUTES", -1)
        expired = create_service_token(client_id=CLIENT_ID, scopes=SCOPE)
        r = client.post("/internal/users/emails",
                        json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401

    def test_missing_auth_is_401(self, client, db_session):
        r = client.post("/internal/users/emails", json={"user_ids": [1]})
        assert r.status_code == 401


class TestSeed:
    """The idempotent provisioning helper."""

    def test_seed_creates_client(self, db_session):
        _seed(db_session)
        rows = db_session.scalars(select(ServiceClient).where(ServiceClient.client_id == CLIENT_ID)).all()
        assert len(rows) == 1
        assert rows[0].scopes == SCOPE
        assert rows[0].client_secret_hash != CLIENT_SECRET  # stored hashed, never plaintext

    def test_seed_is_idempotent(self, db_session):
        _seed(db_session)
        _seed(db_session, secret="rotated-secret", scopes="new:scope")
        rows = db_session.scalars(select(ServiceClient).where(ServiceClient.client_id == CLIENT_ID)).all()
        assert len(rows) == 1
        assert rows[0].scopes == "new:scope"

    def test_seed_does_not_reactivate_a_revoked_client(self, db_session, client):
        """Manual revocation (is_active=False) must survive a re-seed on boot —
        otherwise the seed silently undoes revocation, defeating the registry."""
        c = _seed(db_session)
        c.is_active = False
        db_session.commit()
        # re-seed with a rotated secret, as a restart would
        _seed(db_session, secret="rotated-secret")
        c = db_session.scalar(select(ServiceClient).where(ServiceClient.client_id == CLIENT_ID))
        assert c.is_active is False
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": "rotated-secret",
        })
        assert r.status_code == 401

    def test_seed_secret_verifies(self, db_session, client):
        _seed(db_session)
        # the rotated secret is what the token endpoint must accept
        _seed(db_session, secret="rotated-secret")
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": "rotated-secret",
        })
        assert r.status_code == 200

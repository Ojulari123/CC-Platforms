from jose import jwt
from sqlalchemy import select
from app.models import ServiceClient
from app.schemas.oauth import MAX_LOOKUP_IDS
from app.security.jwt import create_service_token
from app.services.service_clients import (
    FORGE_SCOPES,
    PULSE_SCOPES,
    seed_forge_client,
    seed_pulse_client,
    seed_service_client,
)

CLIENT_ID = "pulse"
CLIENT_SECRET = "s3cret-known-only-to-tests"
SCOPE = "users:read:email"
PROFILE_SCOPE = "users:read:profile"
TOKEN_VERSION_SCOPE = "tokens:verify"
ADMINS_SCOPE = "admins:read"

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

    def test_batch_cap_is_enforced(self, client, db_session):
        _seed(db_session)
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 2))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_batch_at_cap_is_accepted(self, client, db_session):
        _seed(db_session)
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 1))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


class TestProfileLookup:
    def _users(self, client, registered_user, invite_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        eng = invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")
        eng_me = client.get("/me", headers={"Authorization": f"Bearer {eng['access_token']}"}).json()
        return alice, eng_me

    def test_returns_names_and_avatars(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        client.patch("/me", json={"avatar_url": "https://cdn.example.com/alice.png"},
                     headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"})
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"], eng["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        got = {u["user_id"]: u for u in r.json()["users"]}
        assert got[alice["id"]]["first_name"] == "Alice"
        assert got[alice["id"]]["last_name"] == "Anderson"
        assert got[alice["id"]]["avatar_url"] == "https://cdn.example.com/alice.png"
        assert got[alice["id"]]["is_active"] is True
        assert got[eng["id"]]["first_name"] == "Eng"
        assert got[eng["id"]]["avatar_url"] is None

    def test_response_never_carries_email(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "email" not in r.json()["users"][0]
        assert "alice@example.com" not in r.text

    def test_unknown_ids_are_omitted(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"], 999999]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        ids = [u["user_id"] for u in r.json()["users"]]
        assert ids == [alice["id"]]

    def test_unknown_ids_are_named_not_just_missing(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"], 999999, 888888]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["unknown_user_ids"] == [888888, 999999]

    def test_known_ids_are_never_called_unknown(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"], eng["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["unknown_user_ids"] == []

    def test_every_requested_id_is_accounted_for(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        requested = [eng["id"], 999999, alice["id"]]
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/profiles", json={"user_ids": requested},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert {u["user_id"] for u in body["users"]} | set(body["unknown_user_ids"]) == set(requested)

    def test_deactivated_user_is_not_reported_unknown(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        client.post(f"/platform/users/{eng['id']}/deactivate",
                    headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"})
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/profiles", json={"user_ids": [eng["id"]]},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert body["unknown_user_ids"] == []
        assert body["users"][0]["is_active"] is False

    def test_existing_users_array_shape_is_unchanged(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/profiles", json={"user_ids": [alice["id"], 999999]},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert set(body["users"][0]) == {"user_id", "first_name", "last_name", "avatar_url", "is_active"}
        assert [u["user_id"] for u in body["users"]] == [alice["id"]]

    def test_both_lists_are_sorted_by_id(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/profiles",
                           json={"user_ids": [999999, eng["id"], 888888, alice["id"]]},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert [u["user_id"] for u in body["users"]] == sorted([alice["id"], eng["id"]])
        assert body["unknown_user_ids"] == [888888, 999999]

    def test_empty_batch_returns_empty_list(self, client, db_session):
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles", json={"user_ids": []},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"users": [], "unknown_user_ids": []}

    def test_deactivated_user_still_resolves(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        d = client.post(f"/platform/users/{eng['id']}/deactivate",
                        headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"})
        assert d.status_code == 200, d.text
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [eng["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()["users"]
        assert len(body) == 1
        assert body[0]["first_name"] == "Eng"
        assert body[0]["is_active"] is False

    def test_batch_cap_is_enforced(self, client, db_session):
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 2))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_batch_at_cap_is_accepted(self, client, db_session):
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 1))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_email_scope_alone_cannot_read_profiles(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles",
                        json={"user_ids": [alice["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_profile_scope_alone_cannot_read_emails(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=PROFILE_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/emails",
                        json={"user_ids": [alice["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_missing_scope_is_403(self, client, db_session):
        _seed(db_session, scopes="something:else")
        token = _get_service_token(client)
        r = client.post("/internal/users/profiles", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_user_access_token_is_rejected(self, client, db_session, registered_user):
        user_token = registered_user["tokens"]["access_token"]
        r = client.post("/internal/users/profiles", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 401  # decode_service_token rejects token_type before scope check

    def test_missing_auth_is_401(self, client, db_session):
        r = client.post("/internal/users/profiles", json={"user_ids": [1]})
        assert r.status_code == 401


class TestTokenVersionLookup:
    def _users(self, client, registered_user, invite_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        eng = invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")
        eng_me = client.get("/me", headers={"Authorization": f"Bearer {eng['access_token']}"}).json()
        return alice, eng_me

    def test_returns_current_token_version(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions",
                        json={"user_ids": [alice["id"], eng["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        got = {u["user_id"]: u["token_version"] for u in r.json()["users"]}
        assert got == {alice["id"]: 0, eng["id"]: 0}

    def test_version_moves_past_the_tv_in_an_issued_token_after_logout_all(self, client, db_session, registered_user):
        tokens = registered_user["tokens"]
        alice = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
        stale_tv = jwt.get_unverified_claims(tokens["access_token"])["tv"]
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        service_token = _get_service_token(client)

        before = client.post("/internal/users/token-versions", json={"user_ids": [alice["id"]]},
                             headers={"Authorization": f"Bearer {service_token}"}).json()
        assert before["users"][0]["token_version"] == stale_tv

        assert client.post("/auth/logout-all", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 204
        after = client.post("/internal/users/token-versions", json={"user_ids": [alice["id"]]},
                            headers={"Authorization": f"Bearer {service_token}"}).json()
        assert after["users"][0]["token_version"] > stale_tv

    def test_unknown_ids_are_named_not_just_missing(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions",
                        json={"user_ids": [alice["id"], 999999, 888888]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["unknown_user_ids"] == [888888, 999999]
        assert [u["user_id"] for u in r.json()["users"]] == [alice["id"]]

    def test_every_requested_id_is_accounted_for(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        requested = [eng["id"], 999999, alice["id"]]
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/token-versions", json={"user_ids": requested},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert {u["user_id"] for u in body["users"]} | set(body["unknown_user_ids"]) == set(requested)

    def test_known_ids_are_never_called_unknown(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/token-versions", json={"user_ids": [alice["id"], eng["id"]]},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert body["unknown_user_ids"] == []

    def test_deactivated_user_still_resolves(self, client, db_session, registered_user, invite_user):
        alice, eng = self._users(client, registered_user, invite_user)
        assert client.post(f"/platform/users/{eng['id']}/deactivate",
                           headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).status_code == 200
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        body = client.post("/internal/users/token-versions", json={"user_ids": [eng["id"]]},
                           headers={"Authorization": f"Bearer {token}"}).json()
        assert body["unknown_user_ids"] == []
        assert body["users"][0]["token_version"] > 0

    def test_response_carries_no_pii(self, client, db_session, registered_user):
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions", json={"user_ids": [alice["id"]]},
                        headers={"Authorization": f"Bearer {token}"})
        assert set(r.json()["users"][0]) == {"user_id", "token_version"}
        assert "alice@example.com" not in r.text
        assert "Alice" not in r.text

    def test_empty_batch_returns_empty_lists(self, client, db_session):
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions", json={"user_ids": []},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"users": [], "unknown_user_ids": []}

    def test_batch_cap_is_enforced(self, client, db_session):
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 2))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_batch_at_cap_is_accepted(self, client, db_session):
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions",
                        json={"user_ids": list(range(1, MAX_LOOKUP_IDS + 1))},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_missing_scope_is_403(self, client, db_session):
        _seed(db_session, scopes="something:else")
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_email_and_profile_scopes_alone_cannot_read_token_versions(self, client, db_session):
        _seed(db_session, scopes=f"{SCOPE} {PROFILE_SCOPE}")
        token = _get_service_token(client)
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_token_version_scope_alone_cannot_read_emails_or_profiles(self, client, db_session):
        _seed(db_session, scopes=TOKEN_VERSION_SCOPE)
        token = _get_service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/internal/users/emails", json={"user_ids": [1]}, headers=headers).status_code == 403
        assert client.post("/internal/users/profiles", json={"user_ids": [1]}, headers=headers).status_code == 403

    def test_user_access_token_is_rejected(self, client, db_session, registered_user):
        user_token = registered_user["tokens"]["access_token"]
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 401  # decode_service_token rejects token_type before scope check

    def test_missing_auth_is_401(self, client, db_session):
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]})
        assert r.status_code == 401

    def test_malformed_token_is_401(self, client, db_session):
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]},
                        headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401

    def test_expired_token_is_401(self, client, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "SERVICE_TOKEN_EXPIRE_MINUTES", -1)
        expired = create_service_token(client_id=CLIENT_ID, scopes=TOKEN_VERSION_SCOPE)
        r = client.post("/internal/users/token-versions", json={"user_ids": [1]},
                        headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401


class TestSeed:
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
        c = _seed(db_session)
        c.is_active = False
        db_session.commit()
        _seed(db_session, secret="rotated-secret")
        c = db_session.scalar(select(ServiceClient).where(ServiceClient.client_id == CLIENT_ID))
        assert c.is_active is False
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": "rotated-secret",
        })
        assert r.status_code == 401

    def test_pulse_seed_grants_email_profile_token_version_and_admin_scopes(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "PULSE_CLIENT_SECRET", CLIENT_SECRET)
        c = seed_pulse_client(db_session)
        assert c is not None
        assert set(c.scopes.split()) == {SCOPE, PROFILE_SCOPE, TOKEN_VERSION_SCOPE, ADMINS_SCOPE}
        assert c.scopes == PULSE_SCOPES

    def test_a_re_seed_grants_a_newly_added_scope_to_an_existing_row(self, db_session, monkeypatch):
        """How admins:read reached the live Pulse row: no migration, the boot re-seed
        rewrites scopes on a client that already exists."""
        from app.config import settings
        monkeypatch.setattr(settings, "PULSE_CLIENT_SECRET", CLIENT_SECRET)
        c = seed_pulse_client(db_session)
        c.scopes = "users:read:email"
        db_session.commit()
        assert ADMINS_SCOPE in seed_pulse_client(db_session).scopes.split()

    def test_pulse_seed_is_noop_without_secret(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "PULSE_CLIENT_SECRET", "")
        assert seed_pulse_client(db_session) is None

    def test_pulse_seed_is_idempotent_and_keeps_revocation(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "PULSE_CLIENT_SECRET", CLIENT_SECRET)
        c = seed_pulse_client(db_session)
        c.is_active = False
        db_session.commit()
        seed_pulse_client(db_session)
        rows = db_session.scalars(select(ServiceClient).where(ServiceClient.client_id == settings.PULSE_CLIENT_ID)).all()
        assert len(rows) == 1
        assert rows[0].scopes == PULSE_SCOPES
        assert rows[0].is_active is False

    def test_forge_seed_creates_client_with_only_the_verify_scope(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FORGE_CLIENT_SECRET", CLIENT_SECRET)
        c = seed_forge_client(db_session)
        assert c is not None
        assert c.client_id == settings.FORGE_CLIENT_ID
        assert c.scopes == FORGE_SCOPES
        assert set(c.scopes.split()) == {TOKEN_VERSION_SCOPE}
        assert c.client_secret_hash != CLIENT_SECRET
        rows = db_session.scalars(select(ServiceClient).where(ServiceClient.client_id == settings.FORGE_CLIENT_ID)).all()
        assert len(rows) == 1

    def test_forge_seed_is_noop_without_secret(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FORGE_CLIENT_SECRET", "")
        assert seed_forge_client(db_session) is None

    def test_forge_seed_is_idempotent_and_keeps_revocation(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FORGE_CLIENT_SECRET", CLIENT_SECRET)
        c = seed_forge_client(db_session)
        c.is_active = False
        db_session.commit()
        seed_forge_client(db_session)
        rows = db_session.scalars(select(ServiceClient).where(ServiceClient.client_id == settings.FORGE_CLIENT_ID)).all()
        assert len(rows) == 1
        assert rows[0].scopes == FORGE_SCOPES
        assert rows[0].is_active is False

    def test_forge_and_pulse_are_separate_clients(self, db_session, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "PULSE_CLIENT_SECRET", CLIENT_SECRET)
        monkeypatch.setattr(settings, "FORGE_CLIENT_SECRET", "a-different-secret")
        p = seed_pulse_client(db_session)
        f = seed_forge_client(db_session)
        assert p.client_id != f.client_id
        assert p.scopes == PULSE_SCOPES
        assert f.scopes == FORGE_SCOPES

    def test_forge_seeded_credentials_verify_tokens_but_read_no_pii(self, db_session, client, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FORGE_CLIENT_SECRET", CLIENT_SECRET)
        seed_forge_client(db_session)
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": settings.FORGE_CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        })
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.post("/internal/users/token-versions", json={"user_ids": [1]}, headers=headers).status_code == 200
        assert client.post("/internal/users/profiles", json={"user_ids": [1]}, headers=headers).status_code == 403
        assert client.post("/internal/users/emails", json={"user_ids": [1]}, headers=headers).status_code == 403

    def test_seed_secret_verifies(self, db_session, client):
        _seed(db_session)
        _seed(db_session, secret="rotated-secret")
        r = client.post("/oauth/token", json={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": "rotated-secret",
        })
        assert r.status_code == 200


class TestAdminLookup:
    """Pulse has to email whoever can decide a report. GET /departments/{id}/members
    answers that for a person, not for a service, so these are the service-shaped form."""

    def test_department_admins_are_returned_with_their_addresses(self, client, db_session, registered_user, invite_user):
        dept_id = registered_user["dept_id"]
        alice = client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).json()
        invite_user(registered_user["tokens"], dept_id, "eng@example.com", "engineer")
        second = invite_user(registered_user["tokens"], dept_id, "boss@example.com", "admin")
        _seed(db_session, scopes=ADMINS_SCOPE)
        token = _get_service_token(client)

        r = client.get(f"/internal/departments/{dept_id}/admins", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200, r.text
        got = {u["user_id"]: u["email"] for u in r.json()["users"]}
        assert got == {alice["id"]: "alice@example.com", second["user"]["id"]: "boss@example.com"}

    def test_a_department_with_no_admin_returns_nobody(self, client, db_session, registered_user, invite_user):
        other = client.post("/departments", json={"name": "Data"},
                            headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"})
        assert other.status_code in (201, 403), other.text
        _seed(db_session, scopes=ADMINS_SCOPE)
        token = _get_service_token(client)

        r = client.get("/internal/departments/999999/admins", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200
        assert r.json()["users"] == []

    def test_platform_admins_are_returned(self, client, db_session, registered_user):
        from app.models import User
        alice = db_session.scalar(select(User).where(User.email == "alice@example.com"))
        alice.is_platform_admin = True
        db_session.commit()
        _seed(db_session, scopes=ADMINS_SCOPE)
        token = _get_service_token(client)

        r = client.get("/internal/platform-admins", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200, r.text
        assert [u["email"] for u in r.json()["users"]] == ["alice@example.com"]

    def test_a_deactivated_admin_is_left_out(self, client, db_session, registered_user):
        from app.models import User
        alice = db_session.scalar(select(User).where(User.email == "alice@example.com"))
        alice.is_platform_admin = True
        alice.is_active = False
        db_session.commit()
        _seed(db_session, scopes=ADMINS_SCOPE)
        token = _get_service_token(client)

        assert client.get("/internal/platform-admins",
                          headers={"Authorization": f"Bearer {token}"}).json()["users"] == []
        assert client.get(f"/internal/departments/{registered_user['dept_id']}/admins",
                          headers={"Authorization": f"Bearer {token}"}).json()["users"] == []

    def test_the_old_pulse_scopes_cannot_read_admins(self, client, db_session, registered_user):
        _seed(db_session, scopes=f"{SCOPE} {PROFILE_SCOPE} {TOKEN_VERSION_SCOPE}")
        token = _get_service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/internal/platform-admins", headers=headers).status_code == 403
        assert client.get(f"/internal/departments/{registered_user['dept_id']}/admins", headers=headers).status_code == 403

    def test_admins_scope_alone_cannot_read_emails_profiles_or_token_versions(self, client, db_session):
        _seed(db_session, scopes=ADMINS_SCOPE)
        token = _get_service_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/internal/users/emails", json={"user_ids": [1]}, headers=headers).status_code == 403
        assert client.post("/internal/users/profiles", json={"user_ids": [1]}, headers=headers).status_code == 403
        assert client.post("/internal/users/token-versions", json={"user_ids": [1]}, headers=headers).status_code == 403

    def test_an_unauthenticated_call_is_401(self, client, registered_user):
        assert client.get("/internal/platform-admins").status_code == 401
        assert client.get(f"/internal/departments/{registered_user['dept_id']}/admins").status_code == 401

    def test_a_user_token_is_not_a_service_token(self, client, registered_user):
        """The whole reason this endpoint exists is the reverse case, so keep the wall
        pointing both ways: a user's access token cannot open an internal endpoint."""
        headers = {"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}
        assert client.get("/internal/platform-admins", headers=headers).status_code == 401

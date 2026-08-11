from app.config import settings
from tests.conftest import auth

def _signup(client, email="newbie@example.com", password="Test123!password", first="New", last="Bie"):
    return client.post("/auth/signup", json={
        "email": email,
        "password": password,
        "first_name": first,
        "last_name": last,
    })

class TestSignup:
    def test_creates_user_and_returns_token_pair(self, client):
        r = _signup(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["email"] == "newbie@example.com"

    def test_fresh_signup_has_no_memberships(self, client):
        tokens = _signup(client).json()
        me = client.get("/me", headers=auth(tokens)).json()
        assert me["memberships"] == []
        assert me["is_platform_admin"] is False
        assert me["email_verified"] is False

    def test_signup_does_not_create_a_department(self, client, registered_user):
        before = len(client.get("/departments", headers=auth(registered_user["tokens"])).json())
        _signup(client, email="another@example.com")
        after = len(client.get("/departments", headers=auth(registered_user["tokens"])).json())
        assert after == before

    def test_email_is_lowercased(self, client):
        r = _signup(client, email="Newbie@Example.COM")
        assert r.status_code == 201
        assert r.json()["user"]["email"] == "newbie@example.com"

    def test_duplicate_email_is_409(self, client):
        _signup(client)
        r = _signup(client)
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"].lower()

    def test_weak_password_rejected(self, client):
        r = _signup(client, password="weakpass")
        assert r.status_code == 400

    def test_signed_up_user_can_log_in(self, client):
        _signup(client)
        r = client.post("/auth/login", json={"email": "newbie@example.com", "password": "Test123!password"})
        assert r.status_code == 200, r.text

class TestSignupDomainGate:
    def test_empty_allows_any_domain(self, client):
        assert settings.signup_allowed_domains_list == []
        r = _signup(client, email="anyone@gmail.com")
        assert r.status_code == 201, r.text

    def test_allowed_domain_succeeds_when_restricted(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SIGNUP_ALLOWED_DOMAINS", "cyphercrescent.com")
        r = _signup(client, email="staff@cyphercrescent.com")
        assert r.status_code == 201, r.text

    def test_disallowed_domain_is_403_when_restricted(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SIGNUP_ALLOWED_DOMAINS", "cyphercrescent.com")
        r = _signup(client, email="outsider@gmail.com")
        assert r.status_code == 403
        assert "domain" in r.json()["detail"].lower()

    def test_domain_match_is_case_insensitive(self, client, monkeypatch):
        monkeypatch.setattr(settings, "SIGNUP_ALLOWED_DOMAINS", "cyphercrescent.com")
        r = _signup(client, email="staff@CypherCrescent.COM")
        assert r.status_code == 201, r.text

class TestSignupGateStartupWarning:
    def test_empty_allowlist_warns_at_startup(self, caplog):
        import logging
        from fastapi.testclient import TestClient
        from app.main import app

        assert settings.signup_allowed_domains_list == []
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with TestClient(app):
                pass
        assert any("SIGNUP_ALLOWED_DOMAINS is empty" in r.message for r in caplog.records)

    def test_configured_allowlist_stays_quiet(self, caplog, monkeypatch):
        import logging
        from fastapi.testclient import TestClient
        from app.main import app

        monkeypatch.setattr(settings, "SIGNUP_ALLOWED_DOMAINS", "cyphercrescent.com")
        with caplog.at_level(logging.WARNING, logger="app.main"):
            with TestClient(app):
                pass
        assert not [r for r in caplog.records if "SIGNUP_ALLOWED_DOMAINS" in r.message]

class TestPlacement:
    def _signup_id(self, client, email):
        tokens = _signup(client, email=email).json()
        return client.get("/me", headers=auth(tokens)).json()["id"], tokens

    def test_admin_places_signed_up_user(self, client, registered_user):
        user_id, tokens = self._signup_id(client, "placed@example.com")
        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": user_id, "role": "engineer"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text
        assert r.json()["user_id"] == user_id
        assert r.json()["role"] == "engineer"

    def test_placed_user_sees_membership_in_me(self, client, registered_user):
        user_id, tokens = self._signup_id(client, "placed@example.com")
        client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": user_id, "role": "engineer"},
            headers=auth(registered_user["tokens"]),
        )
        # The placed user re-reads /me. A stale token still has no membership
        # claim, but /me reads live from the DB, so it shows up immediately.
        me = client.get("/me", headers=auth(tokens)).json()
        assert len(me["memberships"]) == 1
        assert me["memberships"][0]["dept_id"] == registered_user["dept_id"]
        assert me["memberships"][0]["role"] == "engineer"

    def test_placing_twice_is_409(self, client, registered_user):
        user_id, _ = self._signup_id(client, "placed@example.com")
        body = {"user_id": user_id, "role": "engineer"}
        client.post(f"/departments/{registered_user['dept_id']}/members", json=body, headers=auth(registered_user["tokens"]))
        r = client.post(f"/departments/{registered_user['dept_id']}/members", json=body, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409

    def test_unknown_user_is_404(self, client, registered_user):
        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": 999999, "role": "engineer"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 404

    def test_unknown_department_is_404(self, client, registered_user):
        user_id, _ = self._signup_id(client, "placed@example.com")
        r = client.post(
            "/departments/999999/members",
            json={"user_id": user_id, "role": "engineer"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 404

    def test_non_admin_caller_is_403(self, client, registered_user, engineer_user):
        user_id, _ = self._signup_id(client, "placed@example.com")
        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": user_id, "role": "engineer"},
            headers=auth(engineer_user),
        )
        assert r.status_code == 403

    def test_placing_onto_a_team_in_the_dept_works(self, client, registered_user):
        user_id, _ = self._signup_id(client, "placed@example.com")
        team_id = client.post(
            f"/departments/{registered_user['dept_id']}/teams",
            json={"name": "Platform"},
            headers=auth(registered_user["tokens"]),
        ).json()["id"]
        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": user_id, "role": "engineer", "team_id": team_id},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text
        assert r.json()["team_id"] == team_id

    def test_team_from_another_department_is_400(self, client, registered_user, second_dept):
        user_id, _ = self._signup_id(client, "placed@example.com")
        other_team = client.post(
            f"/departments/{second_dept}/teams",
            json={"name": "Data Infra"},
            headers=auth(registered_user["tokens"]),
        ).json()["id"]
        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": user_id, "role": "engineer", "team_id": other_team},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 400

    def test_places_existing_user_into_a_second_department(self, client, registered_user, second_dept, invite_user):
        eng = invite_user(registered_user["tokens"], registered_user["dept_id"], "multi@example.com", "engineer")
        user_id = client.get("/me", headers=auth(eng)).json()["id"]
        r = client.post(
            f"/departments/{second_dept}/members",
            json={"user_id": user_id, "role": "manager"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text
        me = client.get("/me", headers=auth(eng)).json()
        assert {m["dept_id"] for m in me["memberships"]} == {registered_user["dept_id"], second_dept}

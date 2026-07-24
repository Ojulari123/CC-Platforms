"""Offboarding — the only way to end someone's access to the platform itself.

Removing someone from a department ends their access to that department.
Before deactivation existed, a leaver removed from every department could still
log in indefinitely and hold valid tokens; User.is_active was checked in two
places but nothing ever wrote it."""
from tests.conftest import auth


def _deactivate(client, tokens, user_id):
    return client.post(f"/platform/users/{user_id}/deactivate", headers=auth(tokens))


class TestDeactivate:
    def test_deactivated_user_cannot_log_in(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = _deactivate(client, registered_user["tokens"], eng_id)
        assert r.status_code == 200
        assert r.json()["is_active"] is False

        login = client.post("/auth/login", json={"email": "eng@example.com", "password": "Test123!password"})
        assert login.status_code == 403
        assert "deactivated" in login.json()["detail"].lower()

    def test_existing_sessions_die_immediately(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        _deactivate(client, registered_user["tokens"], eng_id)
        # The token they were holding a moment ago is now useless.
        assert client.get("/me", headers=auth(engineer_user)).status_code == 403
        assert client.post("/auth/refresh", json={"refresh_token": engineer_user["refresh_token"]}).status_code == 401

    def test_account_and_memberships_survive(self, client, registered_user, engineer_user):
        """Deactivation is reversible, so nothing is torn down."""
        dept = registered_user["dept_id"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        _deactivate(client, registered_user["tokens"], eng_id)
        members = client.get(f"/departments/{dept}/members", headers=auth(registered_user["tokens"])).json()
        assert eng_id in [m["user_id"] for m in members["items"]]

    def test_reactivate_restores_access(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        _deactivate(client, registered_user["tokens"], eng_id)
        r = client.post(f"/platform/users/{eng_id}/reactivate", headers=auth(registered_user["tokens"]))
        assert r.status_code == 200 and r.json()["is_active"] is True

        login = client.post("/auth/login", json={"email": "eng@example.com", "password": "Test123!password"})
        assert login.status_code == 200
        me = client.get("/me", headers=auth(login.json())).json()
        assert me["memberships"][0]["dept_id"] == registered_user["dept_id"]

    def test_response_surfaces_what_they_still_run(self, client, registered_user, invite_user):
        """Not blocked, but never silent: you can see what needs reassigning."""
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        team = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin).json()["id"]
        mgr = invite_user(registered_user["tokens"], dept, "mgr@example.com", "manager")
        mgr_id = client.get("/me", headers=auth(mgr)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team}/manager/{mgr_id}", headers=admin)

        body = _deactivate(client, registered_user["tokens"], mgr_id).json()
        assert body["still_leads"] == ["Platform (Engineering)"]
        assert body["still_heads"] == []

    def test_cannot_deactivate_yourself(self, client, registered_user):
        me_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = _deactivate(client, registered_user["tokens"], me_id)
        assert r.status_code == 400
        assert "your own account" in r.json()["detail"]

    def test_the_workspace_cannot_be_locked_out(self, client, registered_user, invite_user):
        """Deactivating requires platform admin, so the only person who could
        deactivate the last platform admin is that person — and the self-check
        stops them. One admin can still deactivate another once a second exists."""
        dept = registered_user["dept_id"]
        bob = invite_user(registered_user["tokens"], dept, "bob@example.com", "admin")
        bob_id = client.get("/me", headers=auth(bob)).json()["id"]
        client.put(f"/platform/admins/{bob_id}", headers=auth(registered_user["tokens"]))
        bob = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()

        alice_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        assert _deactivate(client, bob, alice_id).status_code == 200

        # Bob is now the last platform admin, and the only account able to
        # deactivate him is his own — which is refused.
        r = client.post(f"/platform/users/{bob_id}/deactivate", headers=auth(bob))
        assert r.status_code == 400
        assert "your own account" in r.json()["detail"]

    def test_engineer_cannot_deactivate_anyone(self, client, registered_user, engineer_user):
        alice_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = _deactivate(client, engineer_user, alice_id)
        assert r.status_code == 403
        assert "platform administrator" in r.json()["detail"]

    def test_unknown_user_is_404(self, client, registered_user):
        assert _deactivate(client, registered_user["tokens"], 9999).status_code == 404

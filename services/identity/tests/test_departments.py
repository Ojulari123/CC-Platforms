"""Department endpoints. registered_user (alice) is the department admin.

Note what these tests can no longer do: aim a request at someone else's
department. dept_id comes from the token, so cross-department access isn't
forbidden — it's unreachable. What's left to prove is role gating and that
two departments stay isolated."""


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _dept_id(client, tokens) -> int:
    return client.get("/me", headers=_auth(tokens)).json()["active_dept_id"]


class TestDepartment:
    def test_get_own_department(self, client, registered_user):
        r = client.get("/dept", headers=_auth(registered_user["tokens"]))
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Engineering"
        assert body["slug"] == "engineering"
        assert body["id"] == _dept_id(client, registered_user["tokens"])

    def test_unauthenticated_gets_401(self, client):
        assert client.get("/dept").status_code == 401


class TestTeams:
    def test_admin_creates_team(self, client, registered_user):
        tokens = registered_user["tokens"]
        r = client.post("/dept/teams", json={"name": "Platform Team"}, headers=_auth(tokens))
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Platform Team"
        assert body["slug"] == "platform-team"
        assert body["dept_id"] == _dept_id(client, tokens)

    def test_duplicate_team_name_gets_suffixed_slug(self, client, registered_user):
        tokens = registered_user["tokens"]
        client.post("/dept/teams", json={"name": "Platform"}, headers=_auth(tokens))
        r = client.post("/dept/teams", json={"name": "Platform"}, headers=_auth(tokens))
        assert r.status_code == 201
        assert r.json()["slug"] == "platform-2"

    def test_engineer_cannot_create_team(self, client, engineer_user):
        r = client.post("/dept/teams", json={"name": "Sneaky"}, headers=_auth(engineer_user))
        assert r.status_code == 403
        assert "admin" in r.json()["detail"]

    def test_unauthenticated_gets_401(self, client):
        r = client.post("/dept/teams", json={"name": "X"})
        assert r.status_code == 401

    def test_any_member_can_list_teams(self, client, registered_user, engineer_user):
        tokens = registered_user["tokens"]
        client.post("/dept/teams", json={"name": "Alpha"}, headers=_auth(tokens))
        client.post("/dept/teams", json={"name": "Beta"}, headers=_auth(tokens))
        r = client.get("/dept/teams", headers=_auth(engineer_user))
        assert r.status_code == 200
        assert [t["name"] for t in r.json()] == ["Alpha", "Beta"]

    def test_departments_do_not_see_each_others_teams(self, client, registered_user):
        client.post("/dept/teams", json={"name": "Alice Team"}, headers=_auth(registered_user["tokens"]))
        bob = client.post("/auth/register", json={
            "email": "bob@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "Builder", "dept_name": "Data",
        }).json()
        client.post("/dept/teams", json={"name": "Bob Team"}, headers=_auth(bob))
        assert [t["name"] for t in client.get("/dept/teams", headers=_auth(bob)).json()] == ["Bob Team"]
        assert [t["name"] for t in client.get("/dept/teams", headers=_auth(registered_user["tokens"])).json()] == ["Alice Team"]


class TestMembers:
    def test_list_members_paginated_shape(self, client, registered_user):
        r = client.get("/dept/members", headers=_auth(registered_user["tokens"]))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["limit"] == 50 and body["offset"] == 0
        assert body["items"][0]["email"] == registered_user["email"]
        assert body["items"][0]["role"] == "admin"

    def test_pagination_slices_results(self, client, registered_user, engineer_user):
        tokens = registered_user["tokens"]
        r = client.get("/dept/members?limit=1&offset=0", headers=_auth(tokens))
        assert r.status_code == 200
        assert r.json()["total"] == 2 and len(r.json()["items"]) == 1
        r2 = client.get("/dept/members?limit=1&offset=1", headers=_auth(tokens))
        assert r2.json()["items"][0]["email"] != r.json()["items"][0]["email"]

    def test_update_member_team(self, client, registered_user):
        tokens = registered_user["tokens"]
        team_id = client.post("/dept/teams", json={"name": "Core"}, headers=_auth(tokens)).json()["id"]
        me_id = client.get("/me", headers=_auth(tokens)).json()["id"]
        r = client.patch(f"/dept/members/{me_id}", json={"team_id": team_id}, headers=_auth(tokens))
        assert r.status_code == 200
        assert r.json()["team_id"] == team_id

    def test_engineer_cannot_update_members(self, client, registered_user, engineer_user):
        me_id = client.get("/me", headers=_auth(engineer_user)).json()["id"]
        r = client.patch(f"/dept/members/{me_id}", json={"role": "admin"}, headers=_auth(engineer_user))
        assert r.status_code == 403

    def test_admin_can_promote_engineer_to_manager(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=_auth(engineer_user)).json()["id"]
        r = client.patch(f"/dept/members/{eng_id}", json={"role": "manager"}, headers=_auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["role"] == "manager"

    def test_cannot_demote_last_admin(self, client, registered_user):
        tokens = registered_user["tokens"]
        me_id = client.get("/me", headers=_auth(tokens)).json()["id"]
        r = client.patch(f"/dept/members/{me_id}", json={"role": "engineer"}, headers=_auth(tokens))
        assert r.status_code == 400
        assert "only admin" in r.json()["detail"]

    def test_member_from_another_department_is_404(self, client, registered_user):
        bob = client.post("/auth/register", json={
            "email": "bob2@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "B", "dept_name": "Data Science",
        }).json()
        bob_id = client.get("/me", headers=_auth(bob)).json()["id"]
        r = client.patch(f"/dept/members/{bob_id}", json={"role": "engineer"}, headers=_auth(registered_user["tokens"]))
        assert r.status_code == 404

    def test_team_from_another_department_rejected(self, client, registered_user):
        bob = client.post("/auth/register", json={
            "email": "bob3@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "B", "dept_name": "Bob Department",
        }).json()
        bob_team = client.post("/dept/teams", json={"name": "Bobs"}, headers=_auth(bob)).json()["id"]
        me_id = client.get("/me", headers=_auth(registered_user["tokens"])).json()["id"]
        r = client.patch(f"/dept/members/{me_id}", json={"team_id": bob_team}, headers=_auth(registered_user["tokens"]))
        assert r.status_code == 400

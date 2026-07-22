"""Teams + members endpoints. registered_user (alice) is the org admin."""


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _org_id(client, tokens) -> int:
    return client.get("/me", headers=_auth(tokens)).json()["active_org_id"]


class TestTeams:
    def test_admin_creates_team(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        r = client.post(f"/orgs/{org_id}/teams", json={"name": "Platform Team"}, headers=_auth(tokens))
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Platform Team"
        assert body["slug"] == "platform-team"
        assert body["org_id"] == org_id

    def test_duplicate_team_name_gets_suffixed_slug(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        client.post(f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=_auth(tokens))
        r = client.post(f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=_auth(tokens))
        assert r.status_code == 201
        assert r.json()["slug"] == "platform-2"

    def test_non_member_cannot_create_team(self, client, registered_user):
        org_id = _org_id(client, registered_user["tokens"])
        # Bob registers → gets his own org, is NOT a member of alice's.
        bob = client.post("/auth/register", json={
            "email": "bob@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "Builder", "org_name": "Bob Co",
        }).json()
        r = client.post(f"/orgs/{org_id}/teams", json={"name": "Sneaky"}, headers=_auth(bob))
        assert r.status_code == 403

    def test_unauthenticated_gets_401(self, client, registered_user):
        org_id = _org_id(client, registered_user["tokens"])
        r = client.post(f"/orgs/{org_id}/teams", json={"name": "X"})
        assert r.status_code == 401

    def test_any_member_can_list_teams(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        client.post(f"/orgs/{org_id}/teams", json={"name": "Alpha"}, headers=_auth(tokens))
        client.post(f"/orgs/{org_id}/teams", json={"name": "Beta"}, headers=_auth(tokens))
        r = client.get(f"/orgs/{org_id}/teams", headers=_auth(tokens))
        assert r.status_code == 200
        assert [t["name"] for t in r.json()] == ["Alpha", "Beta"]


class TestMembers:
    def test_list_members_paginated_shape(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        r = client.get(f"/orgs/{org_id}/members", headers=_auth(tokens))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["limit"] == 50 and body["offset"] == 0
        assert body["items"][0]["email"] == registered_user["email"]
        assert body["items"][0]["role"] == "admin"

    def test_update_member_team(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        team_id = client.post(f"/orgs/{org_id}/teams", json={"name": "Core"}, headers=_auth(tokens)).json()["id"]
        me_id = client.get("/me", headers=_auth(tokens)).json()["id"]
        r = client.patch(f"/orgs/{org_id}/members/{me_id}", json={"team_id": team_id}, headers=_auth(tokens))
        assert r.status_code == 200
        assert r.json()["team_id"] == team_id

    def test_cannot_demote_last_admin(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        me_id = client.get("/me", headers=_auth(tokens)).json()["id"]
        r = client.patch(f"/orgs/{org_id}/members/{me_id}", json={"role": "engineer"}, headers=_auth(tokens))
        assert r.status_code == 400
        assert "only admin" in r.json()["detail"]

    def test_team_from_another_org_rejected(self, client, registered_user):
        tokens = registered_user["tokens"]
        org_id = _org_id(client, tokens)
        bob = client.post("/auth/register", json={
            "email": "bob2@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "B", "org_name": "Bob Org",
        }).json()
        bob_org = _org_id(client, bob)
        bob_team = client.post(f"/orgs/{bob_org}/teams", json={"name": "Bobs"}, headers=_auth(bob)).json()["id"]
        me_id = client.get("/me", headers=_auth(tokens)).json()["id"]
        r = client.patch(f"/orgs/{org_id}/members/{me_id}", json={"team_id": bob_team}, headers=_auth(tokens))
        assert r.status_code == 400

"""Departments, their members, and the platform-admin layer above them.

registered_user (alice) is the bootstrap user: platform admin AND admin of
department 1 (Engineering). engineer_user is an ordinary engineer in the same
department — that's the fixture that proves gating actually bites, since alice
passes every check by virtue of being platform admin."""
from tests.conftest import auth


class TestListAndGet:
    def test_member_can_read_own_department(self, client, registered_user):
        r = client.get(f"/departments/{registered_user['dept_id']}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["name"] == "Engineering"
        assert r.json()["slug"] == "engineering"

    def test_any_signed_in_user_can_list_departments(self, client, registered_user, engineer_user, second_dept):
        r = client.get("/departments", headers=auth(engineer_user))
        assert r.status_code == 200
        assert {d["name"] for d in r.json()} == {"Engineering", "Data"}

    def test_unauthenticated_gets_401(self, client, registered_user):
        assert client.get(f"/departments/{registered_user['dept_id']}").status_code == 401

    def test_non_member_cannot_read_a_department(self, client, registered_user, engineer_user, second_dept):
        # The engineer belongs to Engineering only, so Data is off limits.
        r = client.get(f"/departments/{second_dept}", headers=auth(engineer_user))
        assert r.status_code == 403
        assert "Not a member" in r.json()["detail"]

    def test_unknown_department_is_404_for_platform_admin(self, client, registered_user):
        assert client.get("/departments/9999", headers=auth(registered_user["tokens"])).status_code == 404


class TestCreateAndDelete:
    def test_platform_admin_creates_department(self, client, registered_user):
        r = client.post("/departments", json={"name": "Finance Ops"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 201
        assert r.json()["name"] == "Finance Ops"
        assert r.json()["slug"] == "finance-ops"

    def test_duplicate_name_gets_suffixed_slug(self, client, registered_user):
        tokens = registered_user["tokens"]
        client.post("/departments", json={"name": "Data"}, headers=auth(tokens))
        r = client.post("/departments", json={"name": "Data"}, headers=auth(tokens))
        assert r.json()["slug"] == "data-2"

    def test_engineer_cannot_create_department(self, client, registered_user, engineer_user):
        r = client.post("/departments", json={"name": "Shadow IT"}, headers=auth(engineer_user))
        assert r.status_code == 403
        assert "platform administrator" in r.json()["detail"]

    def test_empty_department_can_be_deleted(self, client, registered_user, second_dept):
        assert client.delete(f"/departments/{second_dept}", headers=auth(registered_user["tokens"])).status_code == 204

    def test_department_with_members_cannot_be_deleted(self, client, registered_user):
        r = client.delete(f"/departments/{registered_user['dept_id']}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "member" in r.json()["detail"]


class TestRename:
    def test_dept_admin_renames_and_slug_follows(self, client, registered_user):
        r = client.patch(f"/departments/{registered_user['dept_id']}", json={"name": "Platform Engineering"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["name"] == "Platform Engineering"
        assert r.json()["slug"] == "platform-engineering"

    def test_rename_to_same_name_keeps_clean_slug(self, client, registered_user):
        # Guards the exclude_id logic — without it the department collides with
        # itself and picks up a "-2" suffix.
        dept_id = registered_user["dept_id"]
        r = client.patch(f"/departments/{dept_id}", json={"name": "Engineering"}, headers=auth(registered_user["tokens"]))
        assert r.json()["slug"] == "engineering"

    def test_rename_keeps_same_id(self, client, registered_user):
        dept_id = registered_user["dept_id"]
        r = client.patch(f"/departments/{dept_id}", json={"name": "Renamed"}, headers=auth(registered_user["tokens"]))
        assert r.json()["id"] == dept_id

    def test_engineer_cannot_rename(self, client, registered_user, engineer_user):
        r = client.patch(f"/departments/{registered_user['dept_id']}", json={"name": "Hijacked"}, headers=auth(engineer_user))
        assert r.status_code == 403


class TestMembers:
    def test_list_members_paginated_shape(self, client, registered_user):
        r = client.get(f"/departments/{registered_user['dept_id']}/members", headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["limit"] == 50 and body["offset"] == 0
        assert body["items"][0]["email"] == registered_user["email"]
        assert body["items"][0]["role"] == "admin"

    def test_pagination_slices_results(self, client, registered_user, engineer_user):
        dept_id = registered_user["dept_id"]
        tokens = registered_user["tokens"]
        r = client.get(f"/departments/{dept_id}/members?limit=1&offset=0", headers=auth(tokens))
        assert r.json()["total"] == 2 and len(r.json()["items"]) == 1
        r2 = client.get(f"/departments/{dept_id}/members?limit=1&offset=1", headers=auth(tokens))
        assert r2.json()["items"][0]["email"] != r.json()["items"][0]["email"]

    def test_admin_promotes_engineer_to_manager(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.patch(f"/departments/{registered_user['dept_id']}/members/{eng_id}", json={"role": "manager"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["role"] == "manager"

    def test_engineer_cannot_update_members(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.patch(f"/departments/{registered_user['dept_id']}/members/{eng_id}", json={"role": "admin"}, headers=auth(engineer_user))
        assert r.status_code == 403

    def test_cannot_demote_last_admin(self, client, registered_user):
        me_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = client.patch(f"/departments/{registered_user['dept_id']}/members/{me_id}", json={"role": "engineer"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "only admin" in r.json()["detail"]

    def test_member_of_another_department_is_404(self, client, registered_user, second_dept, invite_user):
        bob = invite_user(registered_user["tokens"], second_dept, "bob@example.com", "engineer")
        bob_id = client.get("/me", headers=auth(bob)).json()["id"]
        # Bob is in Data, not Engineering.
        r = client.patch(f"/departments/{registered_user['dept_id']}/members/{bob_id}", json={"role": "manager"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 404

    def test_team_from_another_department_rejected(self, client, registered_user, second_dept):
        tokens = registered_user["tokens"]
        other_team = client.post(f"/departments/{second_dept}/teams", json={"name": "Data Infra"}, headers=auth(tokens)).json()["id"]
        me_id = client.get("/me", headers=auth(tokens)).json()["id"]
        r = client.patch(f"/departments/{registered_user['dept_id']}/members/{me_id}", json={"team_id": other_team}, headers=auth(tokens))
        assert r.status_code == 400
        assert "does not belong" in r.json()["detail"]


class TestRemoveMember:
    def test_admin_removes_member(self, client, registered_user, engineer_user):
        dept_id, tokens = registered_user["dept_id"], registered_user["tokens"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.delete(f"/departments/{dept_id}/members/{eng_id}", headers=auth(tokens)).status_code == 204
        assert client.get(f"/departments/{dept_id}/members", headers=auth(tokens)).json()["total"] == 1

    def test_removed_member_loses_access_immediately(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.delete(f"/departments/{registered_user['dept_id']}/members/{eng_id}", headers=auth(registered_user["tokens"]))
        assert client.get("/me", headers=auth(engineer_user)).status_code == 401

    def test_removal_keeps_the_account_and_other_departments(self, client, registered_user, second_dept, invite_user):
        """Removing someone from one department must not touch their other one."""
        tokens = registered_user["tokens"]
        bob = invite_user(tokens, second_dept, "bob@example.com", "engineer")
        bob_id = client.get("/me", headers=auth(bob)).json()["id"]
        invite_user(tokens, registered_user["dept_id"], "bob@example.com", "engineer")

        client.delete(f"/departments/{registered_user['dept_id']}/members/{bob_id}", headers=auth(tokens))

        fresh = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()
        me = client.get("/me", headers=auth(fresh)).json()
        assert [m["dept_id"] for m in me["memberships"]] == [second_dept]

    def test_cannot_remove_last_admin(self, client, registered_user):
        me_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = client.delete(f"/departments/{registered_user['dept_id']}/members/{me_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "only admin" in r.json()["detail"]

    def test_engineer_cannot_remove_anyone(self, client, registered_user, engineer_user):
        admin_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = client.delete(f"/departments/{registered_user['dept_id']}/members/{admin_id}", headers=auth(engineer_user))
        assert r.status_code == 403


class TestCrossDepartmentRoles:
    """The bug this restructure exists to fix: one person, two departments,
    different role in each, neither leaking into the other."""

    def test_admin_in_one_department_is_only_an_engineer_in_another(self, client, registered_user, second_dept, invite_user):
        tokens = registered_user["tokens"]
        eng_dept = registered_user["dept_id"]

        # Bob: admin of Data, engineer in Engineering.
        bob = invite_user(tokens, second_dept, "bob@example.com", "admin")
        invite_user(tokens, eng_dept, "bob@example.com", "engineer")
        bob = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()

        roles = {m["dept_id"]: m["role"] for m in client.get("/me", headers=auth(bob)).json()["memberships"]}
        assert roles == {second_dept: "admin", eng_dept: "engineer"}

        # He can rename the department he administers...
        assert client.patch(f"/departments/{second_dept}", json={"name": "Data Platform"}, headers=auth(bob)).status_code == 200
        # ...but not the one where he's an engineer.
        assert client.patch(f"/departments/{eng_dept}", json={"name": "Nope"}, headers=auth(bob)).status_code == 403


class TestPlatformAdmins:
    def test_bootstrap_user_is_platform_admin(self, client, registered_user):
        assert client.get("/me", headers=auth(registered_user["tokens"])).json()["is_platform_admin"] is True

    def test_invited_user_is_not_platform_admin(self, client, engineer_user):
        assert client.get("/me", headers=auth(engineer_user)).json()["is_platform_admin"] is False

    def test_platform_admin_can_administer_a_department_they_are_not_in(self, client, registered_user, second_dept):
        # Alice has no membership in Data, but runs the platform.
        r = client.patch(f"/departments/{second_dept}", json={"name": "Data Science"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 200

    def test_grant_and_list_platform_admins(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.put(f"/platform/admins/{eng_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["is_platform_admin"] is True
        listed = client.get("/platform/admins", headers=auth(registered_user["tokens"])).json()
        assert eng_id in [a["id"] for a in listed]

    def test_granting_forces_a_fresh_token(self, client, registered_user, engineer_user):
        """Their old token still claims is_platform_admin=false, so it's revoked
        rather than left to disagree with the database for 15 minutes."""
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/platform/admins/{eng_id}", headers=auth(registered_user["tokens"]))
        assert client.get("/me", headers=auth(engineer_user)).status_code == 401

        fresh = client.post("/auth/login", json={"email": "eng@example.com", "password": "Test123!password"}).json()
        assert client.get("/me", headers=auth(fresh)).json()["is_platform_admin"] is True
        # And the new privilege actually works.
        assert client.post("/departments", json={"name": "New Dept"}, headers=auth(fresh)).status_code == 201

    def test_engineer_cannot_grant_platform_admin(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.put(f"/platform/admins/{eng_id}", headers=auth(engineer_user)).status_code == 403

    def test_cannot_revoke_the_only_platform_admin(self, client, registered_user):
        me_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        r = client.delete(f"/platform/admins/{me_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "only platform administrator" in r.json()["detail"]

    def test_revoke_works_once_there_are_two(self, client, registered_user, engineer_user):
        tokens = registered_user["tokens"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/platform/admins/{eng_id}", headers=auth(tokens))
        r = client.delete(f"/platform/admins/{eng_id}", headers=auth(tokens))
        assert r.status_code == 200
        assert r.json()["is_platform_admin"] is False


class TestDepartmentHead:
    """Department.head_user_id — the one named person who runs a department,
    as opposed to the SET of people holding role=admin, and distinct again from
    platform admins who run the whole workspace."""

    def _admin_member(self, client, registered_user, invite_user, email="head@example.com"):
        dept = registered_user["dept_id"]
        u = invite_user(registered_user["tokens"], dept, email, "admin")
        return u, client.get("/me", headers=auth(u)).json()["id"]

    def test_department_starts_with_no_head(self, client, registered_user):
        body = client.get(f"/departments/{registered_user['dept_id']}", headers=auth(registered_user["tokens"])).json()
        assert body["head_user_id"] is None
        assert body["head_name"] is None

    def test_platform_admin_names_a_head(self, client, registered_user, invite_user):
        dept = registered_user["dept_id"]
        _, head_id = self._admin_member(client, registered_user, invite_user)
        r = client.put(f"/departments/{dept}/head/{head_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["head_user_id"] == head_id
        assert r.json()["head_name"] == "Head Tester"

    def test_head_must_be_an_admin(self, client, registered_user, engineer_user):
        dept = registered_user["dept_id"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.put(f"/departments/{dept}/head/{eng_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "admin role" in r.json()["detail"]

    def test_head_must_be_in_the_department(self, client, registered_user, second_dept, invite_user):
        outsider = invite_user(registered_user["tokens"], second_dept, "out@example.com", "admin")
        outsider_id = client.get("/me", headers=auth(outsider)).json()["id"]
        r = client.put(f"/departments/{registered_user['dept_id']}/head/{outsider_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "member of this department" in r.json()["detail"]

    def test_naming_a_head_does_not_move_them_to_a_team(self, client, registered_user, invite_user):
        dept = registered_user["dept_id"]
        _, head_id = self._admin_member(client, registered_user, invite_user)
        client.put(f"/departments/{dept}/head/{head_id}", headers=auth(registered_user["tokens"]))
        members = client.get(f"/departments/{dept}/members", headers=auth(registered_user["tokens"])).json()
        assert next(m for m in members["items"] if m["user_id"] == head_id)["team_id"] is None

    def test_head_can_be_cleared(self, client, registered_user, invite_user):
        dept = registered_user["dept_id"]
        _, head_id = self._admin_member(client, registered_user, invite_user)
        client.put(f"/departments/{dept}/head/{head_id}", headers=auth(registered_user["tokens"]))
        r = client.delete(f"/departments/{dept}/head", headers=auth(registered_user["tokens"]))
        assert r.json()["head_user_id"] is None

    def test_dept_admin_cannot_name_the_head(self, client, registered_user, invite_user):
        """Who runs a department is decided from above it."""
        dept = registered_user["dept_id"]
        other, other_id = self._admin_member(client, registered_user, invite_user)
        r = client.put(f"/departments/{dept}/head/{other_id}", headers=auth(other))
        assert r.status_code == 403
        assert "platform administrator" in r.json()["detail"]

    def test_head_shows_in_the_department_list(self, client, registered_user, invite_user):
        dept = registered_user["dept_id"]
        _, head_id = self._admin_member(client, registered_user, invite_user)
        client.put(f"/departments/{dept}/head/{head_id}", headers=auth(registered_user["tokens"]))
        row = next(d for d in client.get("/departments", headers=auth(registered_user["tokens"])).json() if d["id"] == dept)
        assert row["head_name"] == "Head Tester"


class TestRemovingSomeoneInCharge:
    """Nothing may quietly end up with nobody running it."""

    def _lead_of_a_team(self, client, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        team_id = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin).json()["id"]
        mgr = invite_user(registered_user["tokens"], dept, "mgr@example.com", "manager")
        mgr_id = client.get("/me", headers=auth(mgr)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/manager/{mgr_id}", headers=admin)
        return dept, admin, team_id, mgr_id

    def test_removing_a_team_lead_is_refused_with_a_reason(self, client, registered_user, invite_user):
        dept, admin, _, mgr_id = self._lead_of_a_team(client, registered_user, invite_user)
        r = client.delete(f"/departments/{dept}/members/{mgr_id}", headers=admin)
        assert r.status_code == 409
        assert "leads Platform" in r.json()["detail"]
        assert client.get(f"/departments/{dept}/members", headers=admin).json()["total"] == 2

    def test_allow_unled_removes_them_and_empties_the_role(self, client, registered_user, invite_user):
        dept, admin, team_id, mgr_id = self._lead_of_a_team(client, registered_user, invite_user)
        r = client.delete(f"/departments/{dept}/members/{mgr_id}?allow_unled=true", headers=admin)
        assert r.status_code == 204
        assert client.get(f"/departments/{dept}/teams/{team_id}", headers=admin).json()["manager_user_id"] is None

    def test_replacement_takes_over_the_team(self, client, registered_user, invite_user):
        dept, admin, team_id, mgr_id = self._lead_of_a_team(client, registered_user, invite_user)
        successor = invite_user(registered_user["tokens"], dept, "successor@example.com", "manager")
        successor_id = client.get("/me", headers=auth(successor)).json()["id"]

        r = client.delete(f"/departments/{dept}/members/{mgr_id}?replacement_user_id={successor_id}", headers=admin)
        assert r.status_code == 204
        assert client.get(f"/departments/{dept}/teams/{team_id}", headers=admin).json()["manager_user_id"] == successor_id

    def test_replacement_must_be_a_manager_or_admin(self, client, registered_user, invite_user, engineer_user):
        dept, admin, _, mgr_id = self._lead_of_a_team(client, registered_user, invite_user)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.delete(f"/departments/{dept}/members/{mgr_id}?replacement_user_id={eng_id}", headers=admin)
        assert r.status_code == 400
        assert "manager or admin" in r.json()["detail"]

    def test_removing_the_department_head_is_refused(self, client, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        head = invite_user(registered_user["tokens"], dept, "head@example.com", "admin")
        head_id = client.get("/me", headers=auth(head)).json()["id"]
        client.put(f"/departments/{dept}/head/{head_id}", headers=admin)

        r = client.delete(f"/departments/{dept}/members/{head_id}", headers=admin)
        assert r.status_code == 409
        assert "heads Engineering" in r.json()["detail"]

    def test_ordinary_member_removal_is_unaffected(self, client, registered_user, engineer_user):
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.delete(f"/departments/{dept}/members/{eng_id}", headers=admin).status_code == 204


class TestDemotionCannotStrandATitle:
    """A role is checked when a title is granted, never after. Without these
    guards, demoting a team lead to engineer left them still leading the team
    AND still able to manage its roster — permission reads
    Team.manager_user_id, which never re-checks the role."""

    def _lead(self, client, registered_user, invite_user, email="mgr@example.com"):
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        team = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin).json()["id"]
        mgr = invite_user(registered_user["tokens"], dept, email, "manager")
        mgr_id = client.get("/me", headers=auth(mgr)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team}/manager/{mgr_id}", headers=admin)
        return dept, admin, team, mgr, mgr_id

    def test_demoting_a_team_lead_is_refused(self, client, registered_user, invite_user):
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/members/{mgr_id}", json={"role": "engineer"}, headers=admin)
        assert r.status_code == 409
        assert "leads Platform" in r.json()["detail"]
        # Nothing changed: still a manager, still the lead.
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == mgr_id
        members = client.get(f"/departments/{dept}/members", headers=admin).json()["items"]
        assert next(m for m in members if m["user_id"] == mgr_id)["role"] == "manager"

    def test_demotion_with_allow_unled_vacates_the_team(self, client, registered_user, invite_user):
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/members/{mgr_id}?allow_unled=true", json={"role": "engineer"}, headers=admin)
        assert r.status_code == 200
        assert r.json()["role"] == "engineer"
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] is None

    def test_demoted_lead_loses_roster_power(self, client, registered_user, invite_user, engineer_user):
        """The actual privilege bug: demotion must end their access."""
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        client.patch(f"/departments/{dept}/members/{mgr_id}?allow_unled=true", json={"role": "engineer"}, headers=admin)

        fresh = client.post("/auth/login", json={"email": "mgr@example.com", "password": "Test123!password"}).json()
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.put(f"/departments/{dept}/teams/{team}/members/{eng_id}", headers=auth(fresh))
        assert r.status_code == 403

    def test_demotion_with_a_replacement_hands_the_team_over(self, client, registered_user, invite_user):
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        successor = invite_user(registered_user["tokens"], dept, "successor@example.com", "manager")
        successor_id = client.get("/me", headers=auth(successor)).json()["id"]

        r = client.patch(f"/departments/{dept}/members/{mgr_id}?replacement_user_id={successor_id}", json={"role": "engineer"}, headers=admin)
        assert r.status_code == 200
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == successor_id

    def test_manager_to_admin_keeps_the_team(self, client, registered_user, invite_user):
        """Promotion doesn't cost eligibility, so it must not trigger handover."""
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/members/{mgr_id}", json={"role": "admin"}, headers=admin)
        assert r.status_code == 200
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == mgr_id

    def test_admin_to_manager_costs_the_headship_but_not_the_team(self, client, registered_user, invite_user):
        """Heading needs admin; leading only needs manager. So this demotion
        invalidates one title and not the other."""
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        team = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin).json()["id"]
        head = invite_user(registered_user["tokens"], dept, "head@example.com", "admin")
        head_id = client.get("/me", headers=auth(head)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team}/manager/{head_id}", headers=admin)
        client.put(f"/departments/{dept}/head/{head_id}", headers=admin)

        blocked = client.patch(f"/departments/{dept}/members/{head_id}", json={"role": "manager"}, headers=admin)
        assert blocked.status_code == 409
        assert "heads Engineering" in blocked.json()["detail"]
        assert "leads Platform" not in blocked.json()["detail"]

        ok = client.patch(f"/departments/{dept}/members/{head_id}?allow_unled=true", json={"role": "manager"}, headers=admin)
        assert ok.status_code == 200
        assert client.get(f"/departments/{dept}", headers=admin).json()["head_user_id"] is None
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == head_id

    def test_changing_only_the_team_never_triggers_handover(self, client, registered_user, invite_user):
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/members/{mgr_id}", json={"team_id": team}, headers=admin)
        assert r.status_code == 200
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == mgr_id

    def test_demoting_someone_with_no_title_is_unaffected(self, client, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], auth(registered_user["tokens"])
        plain = invite_user(registered_user["tokens"], dept, "plain@example.com", "manager")
        plain_id = client.get("/me", headers=auth(plain)).json()["id"]
        r = client.patch(f"/departments/{dept}/members/{plain_id}", json={"role": "engineer"}, headers=admin)
        assert r.status_code == 200

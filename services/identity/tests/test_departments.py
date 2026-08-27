import pytest
from tests.conftest import auth, refreshed

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

    def test_different_names_that_slugify_alike_get_a_suffixed_slug(self, client, registered_user):
        tokens = registered_user["tokens"]
        client.post("/departments", json={"name": "Data!"}, headers=auth(tokens))
        r = client.post("/departments", json={"name": "Data?"}, headers=auth(tokens))
        assert r.status_code == 201
        assert r.json()["slug"] == "data-2"

    def test_duplicate_name_is_refused(self, client, registered_user, second_dept):
        r = client.post("/departments", json={"name": "Data"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409
        assert r.json()["detail"] == 'A department called "Data" already exists'

    def test_duplicate_name_is_refused_case_and_space_insensitively(self, client, registered_user, second_dept):
        for variant in ("data", "DATA", "  Data  ", "dAtA"):
            r = client.post("/departments", json={"name": variant}, headers=auth(registered_user["tokens"]))
            assert r.status_code == 409, variant
        assert {d["name"] for d in client.get("/departments", headers=auth(registered_user["tokens"])).json()} == {"Engineering", "Data"}

    def test_the_database_refuses_a_duplicate_the_service_check_missed(self, client, registered_user, second_dept, db_session):
        # The index, not the pre-check, is what actually guarantees this — two admins
        # submitting the same name at once both pass the check.
        from sqlalchemy.exc import IntegrityError
        from app.models import Department

        db_session.add(Department(name="dATA", slug="data-clash"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_a_lost_race_on_create_is_a_409_not_a_500(self, client, registered_user, second_dept, monkeypatch):
        # Stand in for the other request having committed between the check and ours.
        from app.services import departments as dept_service
        monkeypatch.setattr(dept_service, "_assert_name_free", lambda *a, **k: None)

        r = client.post("/departments", json={"name": "data"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409
        assert r.json()["detail"] == "A department with that name already exists"

    def test_a_lost_race_on_rename_is_a_409_not_a_500(self, client, registered_user, second_dept, monkeypatch):
        from app.services import departments as dept_service
        monkeypatch.setattr(dept_service, "_assert_name_free", lambda *a, **k: None)

        r = client.patch(f"/departments/{second_dept}", json={"name": "engineering"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409
        assert r.json()["detail"] == "A department with that name already exists"

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
        # Guards the exclude_id logic: without it the department collides with
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

    def test_rename_onto_an_existing_name_is_refused(self, client, registered_user, second_dept):
        r = client.patch(f"/departments/{second_dept}", json={"name": "Engineering"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409
        assert r.json()["detail"] == 'A department called "Engineering" already exists'
        assert client.get(f"/departments/{second_dept}", headers=auth(registered_user["tokens"])).json()["name"] == "Data"

    def test_rename_onto_an_existing_name_is_refused_case_insensitively(self, client, registered_user, second_dept):
        r = client.patch(f"/departments/{second_dept}", json={"name": " engineering "}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 409

    def test_recasing_its_own_name_is_allowed(self, client, registered_user):
        # exclude_id again: a department is never in its own way.
        dept_id = registered_user["dept_id"]
        r = client.patch(f"/departments/{dept_id}", json={"name": "ENGINEERING"}, headers=auth(registered_user["tokens"]))
        assert r.status_code == 200
        assert r.json()["name"] == "ENGINEERING"

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

    def test_list_members_of_unknown_department_404(self, client, registered_user):
        r = client.get("/departments/9999/members", headers=auth(registered_user["tokens"]))
        assert r.status_code == 404
        assert r.json()["detail"] == "Department not found"

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

class TestEmptyingADepartment:
    """The last admin can be neither removed nor demoted, so the only way to empty a
    department for deletion is to move its people somewhere else."""

    def _dept_with_one_admin(self, client, registered_user, invite_user, second_dept) -> tuple[int, int]:
        bob = invite_user(registered_user["tokens"], second_dept, "bob@example.com", "admin")
        return second_dept, client.get("/me", headers=auth(bob)).json()["id"]

    def test_the_last_admin_blocks_removal_demotion_and_the_delete(self, client, registered_user, invite_user, second_dept):
        dept_id, bob_id = self._dept_with_one_admin(client, registered_user, invite_user, second_dept)
        tokens = registered_user["tokens"]
        assert client.delete(f"/departments/{dept_id}/members/{bob_id}", headers=auth(tokens)).status_code == 400
        assert client.patch(f"/departments/{dept_id}/members/{bob_id}", json={"role": "engineer"}, headers=auth(tokens)).status_code == 400
        assert client.delete(f"/departments/{dept_id}", headers=auth(tokens)).status_code == 400

    def test_allow_last_admin_no_longer_buys_anything(self, client, registered_user, invite_user, second_dept):
        # The flag is gone; an old caller still sending it gets the guard, not the escape hatch.
        dept_id, bob_id = self._dept_with_one_admin(client, registered_user, invite_user, second_dept)
        tokens = registered_user["tokens"]
        r = client.delete(f"/departments/{dept_id}/members/{bob_id}?allow_last_admin=true", headers=auth(tokens))
        assert r.status_code == 400
        assert "only admin" in r.json()["detail"]
        assert client.get(f"/departments/{dept_id}/members", headers=auth(tokens)).json()["total"] == 1

    def test_moving_the_last_admin_out_empties_it_and_the_delete_goes_through(self, client, registered_user, invite_user, second_dept):
        dept_id, bob_id = self._dept_with_one_admin(client, registered_user, invite_user, second_dept)
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        r = client.patch(f"/departments/{dept_id}/members/{bob_id}/department", json={"dept_id": eng_dept}, headers=auth(tokens))
        assert r.status_code == 200
        assert client.delete(f"/departments/{dept_id}", headers=auth(tokens)).status_code == 204
        assert {d["name"] for d in client.get("/departments", headers=auth(tokens)).json()} == {"Engineering"}

    def test_the_move_does_not_skip_the_leadership_handover(self, client, registered_user, invite_user, second_dept):
        dept_id, bob_id = self._dept_with_one_admin(client, registered_user, invite_user, second_dept)
        tokens = registered_user["tokens"]
        team_id = client.post(f"/departments/{dept_id}/teams", json={"name": "Data Infra"}, headers=auth(tokens)).json()["id"]
        client.put(f"/departments/{dept_id}/teams/{team_id}/manager/{bob_id}", headers=auth(tokens))

        r = client.patch(f"/departments/{dept_id}/members/{bob_id}/department", json={"dept_id": registered_user["dept_id"]}, headers=auth(tokens))
        assert r.status_code == 409
        assert "leads Data Infra" in r.json()["detail"]

class TestTransferMember:
    def _bob_in(self, client, registered_user, invite_user, dept_id, role="engineer", email="bob@example.com") -> int:
        bob = invite_user(registered_user["tokens"], dept_id, email, role)
        return client.get("/me", headers=auth(bob)).json()["id"]

    def test_move_lands_them_in_the_target_with_their_role(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        bob_id = self._bob_in(client, registered_user, invite_user, eng_dept, "manager")

        r = client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 200
        assert r.json()["role"] == "manager"
        assert r.json()["user_id"] == bob_id

        assert bob_id not in [m["user_id"] for m in client.get(f"/departments/{eng_dept}/members", headers=auth(tokens)).json()["items"]]
        landed = next(m for m in client.get(f"/departments/{second_dept}/members", headers=auth(tokens)).json()["items"] if m["user_id"] == bob_id)
        assert landed["role"] == "manager"

    def test_the_team_does_not_travel_with_them(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        team = client.post(f"/departments/{eng_dept}/teams", json={"name": "Platform"}, headers=auth(tokens)).json()["id"]
        bob_id = self._bob_in(client, registered_user, invite_user, eng_dept)
        client.patch(f"/departments/{eng_dept}/members/{bob_id}", json={"team_id": team}, headers=auth(tokens))

        r = client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 200
        assert r.json()["team_id"] is None

    def test_moving_the_last_admin_is_refused_while_others_remain(self, client, registered_user, invite_user, second_dept, engineer_user):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        me_id = client.get("/me", headers=auth(tokens)).json()["id"]

        r = client.patch(f"/departments/{eng_dept}/members/{me_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 409
        assert "only admin of Engineering" in r.json()["detail"]
        assert "1 member(s)" in r.json()["detail"]
        assert "Move the others out first, or promote another admin" in r.json()["detail"]
        assert client.get(f"/departments/{eng_dept}/members", headers=auth(tokens)).json()["total"] == 2

    def test_moving_the_last_admin_works_once_they_are_the_last_member(self, client, registered_user, invite_user, second_dept, engineer_user):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        me_id = client.get("/me", headers=auth(tokens)).json()["id"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        assert client.patch(f"/departments/{eng_dept}/members/{eng_id}/department", json={"dept_id": second_dept}, headers=auth(tokens)).status_code == 200
        assert client.patch(f"/departments/{eng_dept}/members/{me_id}/department", json={"dept_id": second_dept}, headers=auth(tokens)).status_code == 200
        # Moving themselves bumped their own token_version, so their client refreshes
        # before carrying on. The move is what invalidated the token, not a sign-out.
        tokens = refreshed(client, tokens)
        assert client.delete(f"/departments/{eng_dept}", headers=auth(tokens)).status_code == 204

    def test_moving_the_head_is_refused_until_the_headship_is_dealt_with(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        head_id = self._bob_in(client, registered_user, invite_user, eng_dept, "admin", "head@example.com")
        client.put(f"/departments/{eng_dept}/head/{head_id}", headers=auth(tokens))

        r = client.patch(f"/departments/{eng_dept}/members/{head_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 409
        assert "heads Engineering" in r.json()["detail"]
        assert "Moving them to another department" in r.json()["detail"]

        assert client.delete(f"/departments/{eng_dept}/head", headers=auth(tokens)).status_code == 200
        assert client.patch(f"/departments/{eng_dept}/members/{head_id}/department", json={"dept_id": second_dept}, headers=auth(tokens)).status_code == 200

    def test_a_replacement_takes_over_the_headship_and_the_move_goes_through(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        head_id = self._bob_in(client, registered_user, invite_user, eng_dept, "admin", "head@example.com")
        client.put(f"/departments/{eng_dept}/head/{head_id}", headers=auth(tokens))
        successor_id = client.get("/me", headers=auth(tokens)).json()["id"]

        r = client.patch(f"/departments/{eng_dept}/members/{head_id}/department?replacement_user_id={successor_id}", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 200
        assert client.get(f"/departments/{eng_dept}", headers=auth(tokens)).json()["head_user_id"] == successor_id

    def test_already_a_member_of_the_target_is_a_409(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        bob_id = self._bob_in(client, registered_user, invite_user, eng_dept)
        invite_user(tokens, second_dept, "bob@example.com", "manager")

        r = client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))
        assert r.status_code == 409
        assert "already a member" in r.json()["detail"]
        roles = {m["dept_id"]: m["role"] for m in client.get("/me", headers=auth(client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json())).json()["memberships"]}
        assert roles == {eng_dept: "engineer", second_dept: "manager"}

    def test_moving_into_the_same_department_is_a_400(self, client, registered_user, invite_user):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        bob_id = self._bob_in(client, registered_user, invite_user, eng_dept)
        r = client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": eng_dept}, headers=auth(tokens))
        assert r.status_code == 400
        assert "already a member of that department" in r.json()["detail"]

    def test_unknown_target_department_is_a_404(self, client, registered_user, invite_user):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        bob_id = self._bob_in(client, registered_user, invite_user, eng_dept)
        r = client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": 9999}, headers=auth(tokens))
        assert r.status_code == 404
        assert r.json()["detail"] == "Target department not found"

    def test_admin_of_only_the_source_cannot_move_someone_out(self, client, registered_user, invite_user, second_dept):
        eng_dept = registered_user["dept_id"]
        self._bob_in(client, registered_user, invite_user, eng_dept, "admin")
        victim_id = self._bob_in(client, registered_user, invite_user, eng_dept, "engineer", "victim@example.com")
        bob = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()

        r = client.patch(f"/departments/{eng_dept}/members/{victim_id}/department", json={"dept_id": second_dept}, headers=auth(bob))
        assert r.status_code == 403
        assert "admin role in the department they are moving to" in r.json()["detail"]

    def test_admin_of_both_departments_can_move_someone(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        self._bob_in(client, registered_user, invite_user, eng_dept, "admin")
        invite_user(tokens, second_dept, "bob@example.com", "admin")
        victim_id = self._bob_in(client, registered_user, invite_user, eng_dept, "engineer", "victim@example.com")
        bob = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()

        r = client.patch(f"/departments/{eng_dept}/members/{victim_id}/department", json={"dept_id": second_dept}, headers=auth(bob))
        assert r.status_code == 200

    def test_engineer_cannot_move_anyone(self, client, registered_user, invite_user, second_dept, engineer_user):
        eng_dept = registered_user["dept_id"]
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.patch(f"/departments/{eng_dept}/members/{eng_id}/department", json={"dept_id": second_dept}, headers=auth(engineer_user))
        assert r.status_code == 403

    def test_a_move_does_not_sign_them_out(self, client, registered_user, invite_user, second_dept):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        bob = invite_user(tokens, eng_dept, "bob@example.com", "engineer")
        bob_id = client.get("/me", headers=auth(bob)).json()["id"]

        client.patch(f"/departments/{eng_dept}/members/{bob_id}/department", json={"dept_id": second_dept}, headers=auth(tokens))

        # The token he was holding claims the department he just left, so it is dead the
        # moment the move lands rather than for the rest of its 15 minutes.
        assert client.get("/me", headers=auth(bob)).status_code == 401
        # His refresh token is untouched, which is what keeps this from being a sign-out:
        # no password, no login screen, and the new token names the new department.
        moved = refreshed(client, bob)
        from app.security import decode_access_token
        assert [m["dept_id"] for m in decode_access_token(moved["access_token"])["memberships"]] == [second_dept]
        me = client.get("/me", headers=auth(moved))
        assert me.status_code == 200
        assert [m["dept_id"] for m in me.json()["memberships"]] == [second_dept]

    def test_consolidating_two_departments_end_to_end(self, client, registered_user, invite_user, second_dept):
        tokens, survivor = registered_user["tokens"], registered_user["dept_id"]
        admin_id = self._bob_in(client, registered_user, invite_user, second_dept, "admin", "dup-admin@example.com")
        mgr_id = self._bob_in(client, registered_user, invite_user, second_dept, "manager", "dup-mgr@example.com")
        eng_id = self._bob_in(client, registered_user, invite_user, second_dept, "engineer", "dup-eng@example.com")

        # The admin has to go last: while anyone is behind them the department would be left adminless.
        assert client.patch(f"/departments/{second_dept}/members/{admin_id}/department", json={"dept_id": survivor}, headers=auth(tokens)).status_code == 409
        for user_id in (mgr_id, eng_id, admin_id):
            assert client.patch(f"/departments/{second_dept}/members/{user_id}/department", json={"dept_id": survivor}, headers=auth(tokens)).status_code == 200

        assert client.get(f"/departments/{second_dept}/members", headers=auth(tokens)).json()["total"] == 0
        assert client.delete(f"/departments/{second_dept}", headers=auth(tokens)).status_code == 204
        landed = {m["user_id"]: m["role"] for m in client.get(f"/departments/{survivor}/members", headers=auth(tokens)).json()["items"]}
        assert landed[admin_id] == "admin" and landed[mgr_id] == "manager" and landed[eng_id] == "engineer"

class TestCrossDepartmentRoles:
    def test_admin_in_one_department_is_only_an_engineer_in_another(self, client, registered_user, second_dept, invite_user):
        tokens = registered_user["tokens"]
        eng_dept = registered_user["dept_id"]

        bob = invite_user(tokens, second_dept, "bob@example.com", "admin")
        invite_user(tokens, eng_dept, "bob@example.com", "engineer")
        bob = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test123!password"}).json()

        roles = {m["dept_id"]: m["role"] for m in client.get("/me", headers=auth(bob)).json()["memberships"]}
        assert roles == {second_dept: "admin", eng_dept: "engineer"}

        assert client.patch(f"/departments/{second_dept}", json={"name": "Data Platform"}, headers=auth(bob)).status_code == 200
        assert client.patch(f"/departments/{eng_dept}", json={"name": "Nope"}, headers=auth(bob)).status_code == 403

class TestPlatformAdmins:
    def test_bootstrap_user_is_platform_admin(self, client, registered_user):
        assert client.get("/me", headers=auth(registered_user["tokens"])).json()["is_platform_admin"] is True

    def test_invited_user_is_not_platform_admin(self, client, engineer_user):
        assert client.get("/me", headers=auth(engineer_user)).json()["is_platform_admin"] is False

    def test_platform_admin_can_administer_a_department_they_are_not_in(self, client, registered_user, second_dept):
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
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/platform/admins/{eng_id}", headers=auth(registered_user["tokens"]))
        assert client.get("/me", headers=auth(engineer_user)).status_code == 401

        fresh = client.post("/auth/login", json={"email": "eng@example.com", "password": "Test123!password"}).json()
        assert client.get("/me", headers=auth(fresh)).json()["is_platform_admin"] is True
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
        dept, admin, team, _, mgr_id = self._lead(client, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/members/{mgr_id}", json={"role": "admin"}, headers=admin)
        assert r.status_code == 200
        assert client.get(f"/departments/{dept}/teams/{team}", headers=admin).json()["manager_user_id"] == mgr_id

    def test_admin_to_manager_costs_the_headship_but_not_the_team(self, client, registered_user, invite_user):
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

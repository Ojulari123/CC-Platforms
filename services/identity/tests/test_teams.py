"""Teams, and putting people on them.

A person's team lives on their department membership, so every team operation
is also a check that department scoping holds."""
import pytest

from tests.conftest import auth


@pytest.fixture
def dept(registered_user):
    return registered_user["dept_id"]


@pytest.fixture
def admin(registered_user):
    return auth(registered_user["tokens"])


def _team(client, dept, admin, name="Platform"):
    return client.post(f"/departments/{dept}/teams", json={"name": name}, headers=admin).json()["id"]


class TestTeamCrud:
    def test_admin_creates_team(self, client, dept, admin):
        r = client.post(f"/departments/{dept}/teams", json={"name": "Platform Team"}, headers=admin)
        assert r.status_code == 201
        assert r.json()["name"] == "Platform Team"
        assert r.json()["slug"] == "platform-team"
        assert r.json()["dept_id"] == dept

    def test_duplicate_name_gets_suffixed_slug(self, client, dept, admin):
        client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin)
        r = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin)
        assert r.json()["slug"] == "platform-2"

    def test_same_team_name_allowed_in_different_departments(self, client, dept, admin, second_dept):
        a = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=admin)
        b = client.post(f"/departments/{second_dept}/teams", json={"name": "Platform"}, headers=admin)
        assert a.json()["slug"] == "platform" and b.json()["slug"] == "platform"

    def test_get_single_team(self, client, dept, admin):
        team_id = _team(client, dept, admin)
        r = client.get(f"/departments/{dept}/teams/{team_id}", headers=admin)
        assert r.status_code == 200 and r.json()["id"] == team_id

    def test_rename_team(self, client, dept, admin):
        team_id = _team(client, dept, admin, "Core")
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"name": "Core Platform"}, headers=admin)
        assert r.status_code == 200
        assert r.json()["slug"] == "core-platform"

    def test_rename_to_same_name_keeps_clean_slug(self, client, dept, admin):
        team_id = _team(client, dept, admin, "Core")
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"name": "Core"}, headers=admin)
        assert r.json()["slug"] == "core"

    def test_engineer_cannot_create_or_delete(self, client, dept, admin, engineer_user):
        eng = auth(engineer_user)
        assert client.post(f"/departments/{dept}/teams", json={"name": "Sneaky"}, headers=eng).status_code == 403
        team_id = _team(client, dept, admin)
        assert client.delete(f"/departments/{dept}/teams/{team_id}", headers=eng).status_code == 403

    def test_engineer_can_list_teams(self, client, dept, admin, engineer_user):
        _team(client, dept, admin, "Alpha")
        _team(client, dept, admin, "Beta")
        r = client.get(f"/departments/{dept}/teams", headers=auth(engineer_user))
        assert [t["name"] for t in r.json()] == ["Alpha", "Beta"]

    def test_team_from_another_department_is_404(self, client, dept, admin, second_dept):
        other = _team(client, second_dept, admin, "Data Infra")
        assert client.get(f"/departments/{dept}/teams/{other}", headers=admin).status_code == 404
        assert client.patch(f"/departments/{dept}/teams/{other}", json={"name": "X"}, headers=admin).status_code == 404
        assert client.delete(f"/departments/{dept}/teams/{other}", headers=admin).status_code == 404

    def test_non_member_cannot_list_teams(self, client, second_dept, engineer_user):
        assert client.get(f"/departments/{second_dept}/teams", headers=auth(engineer_user)).status_code == 403


class TestTeamMembers:
    def test_add_and_list_team_members(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)
        assert r.status_code == 200
        assert r.json()["team_id"] == team_id

        members = client.get(f"/departments/{dept}/teams/{team_id}/members", headers=admin).json()
        assert [m["user_id"] for m in members] == [eng_id]

    def test_adding_twice_is_idempotent(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)
        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)
        assert r.status_code == 200
        assert len(client.get(f"/departments/{dept}/teams/{team_id}/members", headers=admin).json()) == 1

    def test_moving_to_another_team_leaves_the_first(self, client, dept, admin, engineer_user):
        """One team per person: joining the second removes them from the first."""
        a = _team(client, dept, admin, "Alpha")
        b = _team(client, dept, admin, "Beta")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        client.put(f"/departments/{dept}/teams/{a}/members/{eng_id}", headers=admin)
        client.put(f"/departments/{dept}/teams/{b}/members/{eng_id}", headers=admin)

        assert client.get(f"/departments/{dept}/teams/{a}/members", headers=admin).json() == []
        assert [m["user_id"] for m in client.get(f"/departments/{dept}/teams/{b}/members", headers=admin).json()] == [eng_id]

    def test_remove_from_team_keeps_them_in_the_department(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)

        assert client.delete(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin).status_code == 204
        assert client.get(f"/departments/{dept}/teams/{team_id}/members", headers=admin).json() == []
        # Still in the department, just unassigned.
        members = client.get(f"/departments/{dept}/members", headers=admin).json()
        assert next(m for m in members["items"] if m["user_id"] == eng_id)["team_id"] is None

    def test_removing_someone_not_on_the_team_is_404(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.delete(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)
        assert r.status_code == 404
        assert "not on this team" in r.json()["detail"]

    def test_cannot_add_someone_from_another_department(self, client, dept, admin, second_dept, registered_user, invite_user):
        team_id = _team(client, dept, admin)
        bob = invite_user(registered_user["tokens"], second_dept, "bob@example.com", "engineer")
        bob_id = client.get("/me", headers=auth(bob)).json()["id"]
        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{bob_id}", headers=admin)
        assert r.status_code == 404
        assert "not a member of this department" in r.json()["detail"]

    def test_engineer_cannot_assign_teams(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(engineer_user))
        assert r.status_code == 403

    def test_deleting_a_team_unassigns_its_members(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)

        assert client.delete(f"/departments/{dept}/teams/{team_id}", headers=admin).status_code == 204
        members = client.get(f"/departments/{dept}/members", headers=admin).json()
        assert next(m for m in members["items"] if m["user_id"] == eng_id)["team_id"] is None

    def test_team_shows_up_on_me(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)

        fresh = client.post("/auth/login", json={"email": "eng@example.com", "password": "Test123!password"}).json()
        membership = client.get("/me", headers=auth(fresh)).json()["memberships"][0]
        assert membership["team_id"] == team_id
        assert membership["team_name"] == "Platform"


class TestTeamLeadRoster:
    """The named lead owns who's on THEIR team — they approve its reports in
    Pulse — but nothing beyond it."""

    def _lead_of(self, client, dept, admin, team_id, registered_user, invite_user, email="mgr@example.com"):
        """Invite a manager and appoint them the team's lead."""
        mgr = invite_user(registered_user["tokens"], dept, email, "manager")
        mgr_id = client.get("/me", headers=auth(mgr)).json()["id"]
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        assert r.status_code == 200, r.text
        return client.post("/auth/login", json={"email": email, "password": "Test123!password"}).json()

    def test_manager_adds_someone_to_their_own_team(self, client, dept, admin, registered_user, invite_user, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        mgr = self._lead_of(client, dept, admin, team_id, registered_user, invite_user)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(mgr))
        assert r.status_code == 200
        assert r.json()["team_id"] == team_id

    def test_manager_removes_someone_from_their_own_team(self, client, dept, admin, registered_user, invite_user, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        mgr = self._lead_of(client, dept, admin, team_id, registered_user, invite_user)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)

        assert client.delete(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(mgr)).status_code == 204

    def test_manager_cannot_touch_another_team(self, client, dept, admin, registered_user, invite_user, engineer_user):
        mine = _team(client, dept, admin, "Platform")
        other = _team(client, dept, admin, "Data Infra")
        mgr = self._lead_of(client, dept, admin, mine, registered_user, invite_user)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        r = client.put(f"/departments/{dept}/teams/{other}/members/{eng_id}", headers=auth(mgr))
        assert r.status_code == 403
        assert "lead of this team" in r.json()["detail"]

    def test_manager_who_is_not_the_lead_cannot_manage(self, client, dept, admin, registered_user, invite_user, engineer_user):
        """Holding the manager role isn't enough — you have to be THE lead."""
        team_id = _team(client, dept, admin, "Platform")
        other = invite_user(registered_user["tokens"], dept, "loose@example.com", "manager")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(other)).status_code == 403

    def test_lead_still_cannot_create_rename_or_delete_teams(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        mgr = self._lead_of(client, dept, admin, team_id, registered_user, invite_user)

        assert client.post(f"/departments/{dept}/teams", json={"name": "New"}, headers=auth(mgr)).status_code == 403
        assert client.patch(f"/departments/{dept}/teams/{team_id}", json={"name": "Renamed"}, headers=auth(mgr)).status_code == 403
        assert client.delete(f"/departments/{dept}/teams/{team_id}", headers=auth(mgr)).status_code == 403

    def test_lead_still_cannot_invite_or_change_roles(self, client, dept, admin, registered_user, invite_user, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        mgr = self._lead_of(client, dept, admin, team_id, registered_user, invite_user)
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        assert client.post(f"/departments/{dept}/invites", json={"email": "x@example.com", "role": "engineer"}, headers=auth(mgr)).status_code == 403
        assert client.patch(f"/departments/{dept}/members/{eng_id}", json={"role": "manager"}, headers=auth(mgr)).status_code == 403

    def test_engineer_still_cannot_manage_rosters(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(engineer_user)).status_code == 403


class TestFlatTeamList:
    """GET /teams — look at teams without knowing a department id first."""

    def test_platform_admin_sees_every_team(self, client, dept, admin, second_dept):
        _team(client, dept, admin, "Platform")
        _team(client, second_dept, admin, "Data Infra")
        r = client.get("/teams", headers=admin)
        assert r.status_code == 200
        assert [(t["name"], t["dept_name"]) for t in r.json()] == [
            ("Data Infra", "Data"), ("Platform", "Engineering"),
        ]

    def test_ordinary_member_sees_only_their_departments(self, client, dept, admin, second_dept, engineer_user):
        _team(client, dept, admin, "Platform")
        _team(client, second_dept, admin, "Data Infra")
        r = client.get("/teams", headers=auth(engineer_user))
        assert [t["name"] for t in r.json()] == ["Platform"]

    def test_includes_member_count(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        assert client.get("/teams", headers=admin).json()[0]["member_count"] == 0

        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=admin)
        assert client.get("/teams", headers=admin).json()[0]["member_count"] == 1

    def test_empty_when_there_are_no_teams(self, client, admin):
        assert client.get("/teams", headers=admin).json() == []

    def test_requires_auth(self, client):
        assert client.get("/teams").status_code == 401


class TestTeamLead:
    """Team.manager_user_id — the single named answer to 'who runs this team',
    and the same one Pulse will use to route report approvals."""

    def _manager(self, client, dept, registered_user, invite_user, email="mgr@example.com"):
        mgr = invite_user(registered_user["tokens"], dept, email, "manager")
        return mgr, client.get("/me", headers=auth(mgr)).json()["id"]

    def test_new_team_has_no_lead(self, client, dept, admin):
        team_id = _team(client, dept, admin, "Platform")
        body = client.get(f"/departments/{dept}/teams/{team_id}", headers=admin).json()
        assert body["manager_user_id"] is None
        assert body["manager_name"] is None

    def test_admin_appoints_a_lead(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        assert r.status_code == 200
        assert r.json()["manager_user_id"] == mgr_id
        assert r.json()["manager_name"] == "Mgr Tester"

    def test_appointing_a_lead_puts_them_on_the_team(self, client, dept, admin, registered_user, invite_user):
        """A lead who isn't a member would be a contradiction, so appointment
        assigns them too."""
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        roster = client.get(f"/departments/{dept}/teams/{team_id}/members", headers=admin).json()
        assert mgr_id in [m["user_id"] for m in roster]

    def test_engineer_cannot_be_made_lead(self, client, dept, admin, engineer_user):
        team_id = _team(client, dept, admin, "Platform")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": eng_id}, headers=admin)
        assert r.status_code == 400
        assert "manager or admin role" in r.json()["detail"]

    def test_lead_must_be_in_the_department(self, client, dept, admin, second_dept, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        outsider = invite_user(registered_user["tokens"], second_dept, "outsider@example.com", "manager")
        outsider_id = client.get("/me", headers=auth(outsider)).json()["id"]
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": outsider_id}, headers=admin)
        assert r.status_code == 400
        assert "member of this department" in r.json()["detail"]

    def test_lead_can_be_cleared(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": None}, headers=admin)
        assert r.json()["manager_user_id"] is None

    def test_renaming_does_not_disturb_the_lead(self, client, dept, admin, registered_user, invite_user):
        """PATCH is partial — omitting manager_user_id leaves it alone."""
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"name": "Core Platform"}, headers=admin)
        assert r.json()["name"] == "Core Platform"
        assert r.json()["manager_user_id"] == mgr_id

    def test_taking_the_lead_off_the_team_vacates_the_role(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)

        client.delete(f"/departments/{dept}/teams/{team_id}/members/{mgr_id}", headers=admin)
        body = client.get(f"/departments/{dept}/teams/{team_id}", headers=admin).json()
        assert body["manager_user_id"] is None

    def test_removing_the_lead_from_the_department_vacates_the_role(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)

        client.delete(f"/departments/{dept}/members/{mgr_id}", headers=admin)
        body = client.get(f"/departments/{dept}/teams/{team_id}", headers=admin).json()
        assert body["manager_user_id"] is None

    def test_lead_appears_in_the_flat_team_list(self, client, dept, admin, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=admin)
        row = client.get("/teams", headers=admin).json()[0]
        assert row["manager_user_id"] == mgr_id
        assert row["manager_name"] == "Mgr Tester"

    def test_engineer_cannot_appoint_a_lead(self, client, dept, admin, engineer_user, registered_user, invite_user):
        team_id = _team(client, dept, admin, "Platform")
        _, mgr_id = self._manager(client, dept, registered_user, invite_user)
        r = client.patch(f"/departments/{dept}/teams/{team_id}", json={"manager_user_id": mgr_id}, headers=auth(engineer_user))
        assert r.status_code == 403

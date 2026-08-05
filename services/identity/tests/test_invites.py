from tests.conftest import auth

def _invite(client, tokens, dept_id, email="dami@example.com", role="engineer", team_id=None):
    return client.post(
        f"/departments/{dept_id}/invites",
        json={"email": email, "role": role, "team_id": team_id},
        headers=auth(tokens),
    )

def _accept(client, token, first="Dami", last="Ebire", password="Test123!password"):
    return client.post("/invites/accept", json={
        "token": token, "first_name": first, "last_name": last, "password": password,
    })

class TestCreateInvite:
    def test_admin_can_invite(self, client, registered_user, sent_emails):
        r = _invite(client, registered_user["tokens"], registered_user["dept_id"])
        assert r.status_code == 201
        assert r.json()["email"] == "dami@example.com"
        assert r.json()["role"] == "engineer"
        assert len(sent_emails) == 1
        assert sent_emails[0]["to"] == "dami@example.com"
        assert sent_emails[0]["dept_name"] == "Engineering"
        assert sent_emails[0]["raw_token"]

    def test_email_not_configured_returns_503(self, client, registered_user):
        # No monkeypatch here — send_invite runs for real and hits the guard
        # (test env has no BREVO_API_KEY). Also proves a failed send rolls back.
        r = _invite(client, registered_user["tokens"], registered_user["dept_id"])
        assert r.status_code == 503

    def test_failed_send_leaves_no_invite_behind(self, client, registered_user):
        dept_id = registered_user["dept_id"]
        _invite(client, registered_user["tokens"], dept_id)  # 503, email not configured
        listed = client.get(f"/departments/{dept_id}/invites", headers=auth(registered_user["tokens"]))
        assert listed.json() == []

    def test_engineer_cannot_invite(self, client, registered_user, engineer_user, sent_emails):
        r = _invite(client, engineer_user, registered_user["dept_id"], email="friend@example.com")
        assert r.status_code == 403

    def test_cannot_invite_existing_member(self, client, registered_user, sent_emails):
        r = _invite(client, registered_user["tokens"], registered_user["dept_id"], email=registered_user["email"])
        assert r.status_code == 400
        assert "already a member" in r.json()["detail"]

    def test_can_invite_someone_who_is_in_another_department(self, client, registered_user, second_dept, invite_user, sent_emails):
        """Being in Data must not block an invite into Engineering."""
        invite_user(registered_user["tokens"], second_dept, "bob@example.com", "engineer")
        r = _invite(client, registered_user["tokens"], registered_user["dept_id"], email="bob@example.com")
        assert r.status_code == 201

    def test_team_must_belong_to_the_department(self, client, registered_user, second_dept, sent_emails):
        tokens = registered_user["tokens"]
        other_team = client.post(f"/departments/{second_dept}/teams", json={"name": "Data Infra"}, headers=auth(tokens)).json()["id"]
        r = _invite(client, tokens, registered_user["dept_id"], team_id=other_team)
        assert r.status_code == 400
        assert "does not belong" in r.json()["detail"]

    def test_reinvite_replaces_pending_invite(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        _invite(client, tokens, dept_id)
        _invite(client, tokens, dept_id, role="manager")
        old, new = sent_emails[0]["raw_token"], sent_emails[1]["raw_token"]
        assert _accept(client, old).status_code == 400
        assert _accept(client, new).status_code == 200

class TestAcceptInvite:
    def test_new_user_joins_inviting_department(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        _invite(client, tokens, dept_id, role="engineer")
        r = _accept(client, sent_emails[0]["raw_token"])
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] and body["refresh_token"]

        me = client.get("/me", headers=auth(body)).json()
        assert [m["dept_id"] for m in me["memberships"]] == [dept_id]
        assert me["memberships"][0]["role"] == "engineer"
        assert me["email_verified"] is True
        assert me["is_platform_admin"] is False

        assert client.get(f"/departments/{dept_id}/members", headers=auth(tokens)).json()["total"] == 2

    def test_new_user_without_password_rejected(self, client, registered_user, sent_emails):
        _invite(client, registered_user["tokens"], registered_user["dept_id"])
        r = client.post("/invites/accept", json={"token": sent_emails[0]["raw_token"]})
        assert r.status_code == 400
        assert "required" in r.json()["detail"]

    def test_weak_password_rejected(self, client, registered_user, sent_emails):
        _invite(client, registered_user["tokens"], registered_user["dept_id"])
        r = _accept(client, sent_emails[0]["raw_token"], password="weakpass")
        assert r.status_code == 400

    def test_existing_user_gains_a_second_membership(self, client, registered_user, second_dept, invite_user, sent_emails):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        invite_user(tokens, second_dept, "bob@example.com", "admin")

        _invite(client, tokens, eng_dept, email="bob@example.com", role="engineer")
        r = client.post("/invites/accept", json={"token": sent_emails[-1]["raw_token"]})
        assert r.status_code == 200

        me = client.get("/me", headers=auth(r.json())).json()
        roles = {m["dept_id"]: m["role"] for m in me["memberships"]}
        assert roles == {second_dept: "admin", eng_dept: "engineer"}

    def test_bogus_token_rejected(self, client):
        assert _accept(client, "nonsense").status_code == 400

    def test_invite_single_use(self, client, registered_user, sent_emails):
        _invite(client, registered_user["tokens"], registered_user["dept_id"])
        token = sent_emails[0]["raw_token"]
        assert _accept(client, token).status_code == 200
        r = _accept(client, token)
        assert r.status_code == 400
        assert "already been used" in r.json()["detail"]

    def test_invited_team_is_assigned(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        team_id = client.post(f"/departments/{dept_id}/teams", json={"name": "Platform"}, headers=auth(tokens)).json()["id"]
        _invite(client, tokens, dept_id, team_id=team_id)
        r = _accept(client, sent_emails[0]["raw_token"])
        assert r.status_code == 200
        me = client.get("/me", headers=auth(r.json())).json()
        assert me["memberships"][0]["team_id"] == team_id
        assert me["memberships"][0]["team_name"] == "Platform"

class TestListRevokeInvites:
    def test_admin_lists_pending_invites(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        _invite(client, tokens, dept_id, email="a@example.com")
        _invite(client, tokens, dept_id, email="b@example.com", role="manager")
        r = client.get(f"/departments/{dept_id}/invites", headers=auth(tokens))
        assert r.status_code == 200
        assert {i["email"] for i in r.json()} == {"a@example.com", "b@example.com"}

    def test_accepted_invites_drop_off_the_list(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        _invite(client, tokens, dept_id)
        _accept(client, sent_emails[0]["raw_token"])
        assert client.get(f"/departments/{dept_id}/invites", headers=auth(tokens)).json() == []

    def test_engineer_cannot_list_invites(self, client, registered_user, engineer_user):
        r = client.get(f"/departments/{registered_user['dept_id']}/invites", headers=auth(engineer_user))
        assert r.status_code == 403

    def test_revoked_invite_link_stops_working(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        invite_id = _invite(client, tokens, dept_id).json()["id"]
        assert client.delete(f"/departments/{dept_id}/invites/{invite_id}", headers=auth(tokens)).status_code == 204
        assert _accept(client, sent_emails[0]["raw_token"]).status_code == 400

    def test_invites_are_scoped_to_their_department(self, client, registered_user, second_dept, sent_emails):
        tokens, eng_dept = registered_user["tokens"], registered_user["dept_id"]
        invite_id = _invite(client, tokens, eng_dept).json()["id"]
        # Same invite id, wrong department in the path.
        r = client.delete(f"/departments/{second_dept}/invites/{invite_id}", headers=auth(tokens))
        assert r.status_code == 404

class TestInvitePreview:
    def test_preview_shows_department_and_role(self, client, registered_user, sent_emails):
        _invite(client, registered_user["tokens"], registered_user["dept_id"], role="manager")
        r = client.get(f"/invites/preview?token={sent_emails[0]['raw_token']}")
        assert r.status_code == 200
        body = r.json()
        assert body["dept_name"] == "Engineering"
        assert body["role"] == "manager"
        assert body["email"] == "dami@example.com"
        assert body["needs_account"] is True

    def test_preview_flags_existing_account(self, client, registered_user, second_dept, invite_user, sent_emails):
        invite_user(registered_user["tokens"], second_dept, "bob@example.com", "engineer")
        _invite(client, registered_user["tokens"], registered_user["dept_id"], email="bob@example.com")
        r = client.get(f"/invites/preview?token={sent_emails[-1]['raw_token']}")
        assert r.json()["needs_account"] is False

    def test_preview_rejects_bogus_token(self, client):
        assert client.get("/invites/preview?token=nonsense").status_code == 400

class TestInviteStraightOntoATeam:
    """You can hire someone into a team, not just a department — the invite
    carries an optional team_id and the invitee lands on it already assigned."""

    def test_email_and_preview_name_the_team(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        team_id = client.post(f"/departments/{dept_id}/teams", json={"name": "Platform"}, headers=auth(tokens)).json()["id"]
        _invite(client, tokens, dept_id, team_id=team_id)

        assert sent_emails[0]["team_name"] == "Platform"
        preview = client.get(f"/invites/preview?token={sent_emails[0]['raw_token']}").json()
        assert preview["team_name"] == "Platform"
        assert preview["dept_name"] == "Engineering"

    def test_no_team_means_no_team_name(self, client, registered_user, sent_emails):
        _invite(client, registered_user["tokens"], registered_user["dept_id"])
        assert sent_emails[0]["team_name"] is None
        preview = client.get(f"/invites/preview?token={sent_emails[0]['raw_token']}").json()
        assert preview["team_name"] is None

    def test_invitee_shows_up_on_the_team_roster(self, client, registered_user, sent_emails):
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        team_id = client.post(f"/departments/{dept_id}/teams", json={"name": "Platform"}, headers=auth(tokens)).json()["id"]
        _invite(client, tokens, dept_id, team_id=team_id)
        accepted = _accept(client, sent_emails[0]["raw_token"])
        assert accepted.status_code == 200

        roster = client.get(f"/departments/{dept_id}/teams/{team_id}/members", headers=auth(tokens)).json()
        assert [m["email"] for m in roster] == ["dami@example.com"]

    def test_unassigned_invitee_can_be_added_to_a_team_afterwards(self, client, registered_user, sent_emails):
        """The other path: join the department first, get a team later."""
        tokens, dept_id = registered_user["tokens"], registered_user["dept_id"]
        _invite(client, tokens, dept_id)
        accepted = _accept(client, sent_emails[0]["raw_token"]).json()
        me = client.get("/me", headers=auth(accepted)).json()
        user_id = me["id"]
        assert me["memberships"][0]["team_id"] is None

        team_id = client.post(f"/departments/{dept_id}/teams", json={"name": "Platform"}, headers=auth(tokens)).json()["id"]
        assert client.put(f"/departments/{dept_id}/teams/{team_id}/members/{user_id}", headers=auth(tokens)).status_code == 200

        fresh = client.post("/auth/login", json={"email": "dami@example.com", "password": "Test123!password"}).json()
        assert client.get("/me", headers=auth(fresh)).json()["memberships"][0]["team_name"] == "Platform"

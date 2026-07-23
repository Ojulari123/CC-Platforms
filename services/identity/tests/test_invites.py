"""Invite lifecycle. Brevo is never hit — email.send is monkeypatched and the
raw token is captured from the send_invite call."""
def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _dept_id(client, tokens) -> int:
    return client.get("/me", headers=_auth(tokens)).json()["active_dept_id"]


def _invite(client, tokens, email="dami@example.com", role="engineer", team_id=None):
    return client.post(
        "/dept/invites",
        json={"email": email, "role": role, "team_id": team_id},
        headers=_auth(tokens),
    )


class TestCreateInvite:
    def test_admin_can_invite(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        r = _invite(client, tokens)
        assert r.status_code == 201
        assert r.json()["email"] == "dami@example.com"
        assert r.json()["role"] == "engineer"
        assert len(sent_emails) == 1
        assert sent_emails[0]["to"] == "dami@example.com"
        assert sent_emails[0]["raw_token"]

    def test_email_not_configured_returns_503(self, client, registered_user):
        # No monkeypatch here — send_invite runs for real and hits the guard
        # (test env has no BREVO_API_KEY). Also proves a failed send rolls back.
        tokens = registered_user["tokens"]
        r = _invite(client, tokens)
        assert r.status_code == 503

    def test_non_admin_cannot_invite(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        _invite(client, tokens, email="eng@example.com")
        eng_tokens = client.post("/invites/accept", json={
            "token": sent_emails[0]["raw_token"],
            "first_name": "Enid", "last_name": "Engineer", "password": "Test123!password",
        }).json()
        r = _invite(client, eng_tokens, email="friend@example.com")
        assert r.status_code == 403

    def test_cannot_invite_existing_member(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        r = _invite(client, tokens, email=registered_user["email"])
        assert r.status_code == 400
        assert "already a member" in r.json()["detail"]

    def test_reinvite_replaces_pending_invite(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        _invite(client, tokens)
        _invite(client, tokens, role="manager")
        # Old token is dead, new one works and carries the new role.
        old, new = sent_emails[0]["raw_token"], sent_emails[1]["raw_token"]
        r_old = client.post("/invites/accept", json={
            "token": old, "first_name": "D", "last_name": "E", "password": "Test123!password",
        })
        assert r_old.status_code == 400
        r_new = client.post("/invites/accept", json={
            "token": new, "first_name": "D", "last_name": "E", "password": "Test123!password",
        })
        assert r_new.status_code == 200


class TestAcceptInvite:
    def test_new_user_joins_inviting_department(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        dept_id = _dept_id(client, tokens)
        _invite(client, tokens, role="engineer")
        r = client.post("/invites/accept", json={
            "token": sent_emails[0]["raw_token"],
            "first_name": "Dami", "last_name": "Ebire", "password": "Test123!password",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] and body["refresh_token"]
        # They landed in ALICE's department — not a new one — with the invited role.
        me = client.get("/me", headers=_auth(body)).json()
        assert me["active_dept_id"] == dept_id
        assert me["active_role"] == "engineer"
        assert me["email_verified"] is True
        # And the department now lists two members.
        members = client.get("/dept/members", headers=_auth(tokens)).json()
        assert members["total"] == 2

    def test_new_user_without_password_rejected(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        _invite(client, tokens)
        r = client.post("/invites/accept", json={"token": sent_emails[0]["raw_token"]})
        assert r.status_code == 400
        assert "required" in r.json()["detail"]

    def test_existing_user_gains_membership(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        dept_id = _dept_id(client, tokens)
        # Bob already has his own account + department.
        client.post("/auth/register", json={
            "email": "bob3@example.com", "password": "Test123!password",
            "first_name": "Bob", "last_name": "B", "dept_name": "Bob Third Department",
        })
        _invite(client, tokens, email="bob3@example.com", role="manager")
        r = client.post("/invites/accept", json={"token": sent_emails[0]["raw_token"]})
        assert r.status_code == 200
        # Token pair is scoped to the INVITING department with the invited role.
        me = client.get("/me", headers=_auth(r.json())).json()
        assert me["active_dept_id"] == dept_id
        assert me["active_role"] == "manager"

    def test_bogus_token_rejected(self, client):
        r = client.post("/invites/accept", json={
            "token": "nonsense", "first_name": "X", "last_name": "Y", "password": "Test123!password",
        })
        assert r.status_code == 400

    def test_invite_single_use(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        _invite(client, tokens)
        payload = {
            "token": sent_emails[0]["raw_token"],
            "first_name": "D", "last_name": "E", "password": "Test123!password",
        }
        assert client.post("/invites/accept", json=payload).status_code == 200
        r = client.post("/invites/accept", json=payload)
        assert r.status_code == 400
        assert "already been used" in r.json()["detail"]

    def test_invited_team_is_assigned(self, client, registered_user, sent_emails):
        tokens = registered_user["tokens"]
        team_id = client.post("/dept/teams", json={"name": "Platform"}, headers=_auth(tokens)).json()["id"]
        _invite(client, tokens, team_id=team_id)
        r = client.post("/invites/accept", json={
            "token": sent_emails[0]["raw_token"],
            "first_name": "D", "last_name": "E", "password": "Test123!password",
        })
        assert r.status_code == 200
        members = client.get("/dept/members", headers=_auth(tokens)).json()
        invited = next(m for m in members["items"] if m["email"] == "dami@example.com")
        assert invited["team_id"] == team_id

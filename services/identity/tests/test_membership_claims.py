"""Membership changes have to reach the products holding a token, not sit behind the
access token's 15 minutes. Every case below asserts the same three things: the change
bumps token_version, the token they were holding stops working, and their refresh token
still works and comes back with the corrected claims. That last one is the point — this
is a permissions correction, not a sign-out.
"""
from sqlalchemy import select
from app import revocations
from app.models import RefreshToken, User
from app.security import decode_access_token
from tests.conftest import auth, refreshed

def _version(db_session, user_id: int) -> int:
    db_session.expire_all()  # the request that changed it committed on a different session
    return db_session.get(User, user_id).token_version

def _id_of(client, tokens: dict) -> int:
    return client.get("/me", headers=auth(tokens)).json()["id"]

def _claims(tokens: dict) -> dict:
    return decode_access_token(tokens["access_token"])

def _live_refresh_tokens(db_session, user_id: int) -> int:
    return len(list(db_session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
    )))

def _signup(client, email: str) -> dict:
    r = client.post("/auth/signup", json={
        "email": email, "password": "Test123!password", "first_name": "New", "last_name": "Bie",
    })
    assert r.status_code == 201, r.text
    return r.json()

def _team(client, dept_id: int, admin_tokens: dict, name: str) -> int:
    r = client.post(f"/departments/{dept_id}/teams", json={"name": name}, headers=auth(admin_tokens))
    assert r.status_code == 201, r.text
    return r.json()["id"]

class TestDepartmentMembership:
    def test_being_added_to_a_department_lands_within_seconds(self, client, db_session, registered_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        joiner = _signup(client, "joiner@example.com")
        joiner_id = _id_of(client, joiner)
        before = _version(db_session, joiner_id)

        r = client.post(f"/departments/{dept}/members", json={"user_id": joiner_id, "role": "engineer"}, headers=auth(admin))
        assert r.status_code == 201, r.text

        assert _version(db_session, joiner_id) == before + 1
        assert client.get("/me", headers=auth(joiner)).status_code == 401
        fresh = refreshed(client, joiner)
        assert _claims(fresh)["memberships"] == [{"dept_id": dept, "team_id": None, "role": "engineer"}]

    def test_a_demotion_stops_the_old_token_claiming_admin(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "admin")
        bob_id = _id_of(client, bob)
        assert _claims(bob).role_in(dept) == "admin"
        before = _version(db_session, bob_id)

        r = client.patch(f"/departments/{dept}/members/{bob_id}", json={"role": "engineer"}, headers=auth(admin))
        assert r.status_code == 200, r.text

        # The whole reason this matters: Pulse reads approval authority off role_in().
        assert _version(db_session, bob_id) == before + 1
        assert client.get("/me", headers=auth(bob)).status_code == 401
        assert _claims(refreshed(client, bob)).role_in(dept) == "engineer"

    def test_a_demotion_does_not_cost_them_their_session(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "admin")
        bob_id = _id_of(client, bob)

        client.patch(f"/departments/{dept}/members/{bob_id}", json={"role": "engineer"}, headers=auth(admin))

        assert _live_refresh_tokens(db_session, bob_id) == 1
        assert client.post("/auth/refresh", json={"refresh_token": bob["refresh_token"]}).status_code == 200

    def test_a_move_between_departments_lands_within_seconds(self, client, db_session, registered_user, invite_user, second_dept):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        r = client.patch(f"/departments/{dept}/members/{bob_id}/department", json={"dept_id": second_dept}, headers=auth(admin))
        assert r.status_code == 200, r.text

        assert _version(db_session, bob_id) == before + 1
        assert client.get("/me", headers=auth(bob)).status_code == 401
        assert [m["dept_id"] for m in _claims(refreshed(client, bob)).memberships] == [second_dept]

    def test_a_team_move_lands_within_seconds(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        r = client.patch(f"/departments/{dept}/members/{bob_id}", json={"team_id": team_id}, headers=auth(admin))
        assert r.status_code == 200, r.text

        assert _version(db_session, bob_id) == before + 1
        assert _claims(refreshed(client, bob)).memberships[0]["team_id"] == team_id

    def test_a_patch_that_changes_nothing_does_not_bump(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        assert client.patch(f"/departments/{dept}/members/{bob_id}", json={}, headers=auth(admin)).status_code == 200

        assert _version(db_session, bob_id) == before
        assert client.get("/me", headers=auth(bob)).status_code == 200

class TestRemoval:
    """Removal used to call revoke_all_for_user, which killed the refresh tokens as well
    and signed the person out of every device they owned. Losing a department is an
    authorisation change — they may still be in others — so it bumps like the rest."""

    def test_removal_kills_the_old_token(self, client, db_session, registered_user, invite_user, second_dept):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        client.post(f"/departments/{second_dept}/members", json={"user_id": bob_id, "role": "engineer"}, headers=auth(admin))
        bob = refreshed(client, bob)
        before = _version(db_session, bob_id)

        assert client.delete(f"/departments/{dept}/members/{bob_id}", headers=auth(admin)).status_code == 204

        assert _version(db_session, bob_id) == before + 1
        assert client.get("/me", headers=auth(bob)).status_code == 401

    def test_removal_leaves_their_sessions_alone(self, client, db_session, registered_user, invite_user, second_dept):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        client.post(f"/departments/{second_dept}/members", json={"user_id": bob_id, "role": "engineer"}, headers=auth(admin))
        bob = refreshed(client, bob)

        client.delete(f"/departments/{dept}/members/{bob_id}", headers=auth(admin))

        assert _live_refresh_tokens(db_session, bob_id) == 1
        # Still signed in, and the department they were taken out of is gone from the claims.
        assert [m["dept_id"] for m in _claims(refreshed(client, bob)).memberships] == [second_dept]

    def test_their_last_department_leaves_them_signed_in_with_nothing(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)

        client.delete(f"/departments/{dept}/members/{bob_id}", headers=auth(admin))

        fresh = refreshed(client, bob)
        assert _claims(fresh).memberships == []
        assert client.get("/me", headers=auth(fresh)).status_code == 200

class TestTeamLeadership:
    def test_being_handed_a_team_lands_within_seconds(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        mgr = invite_user(admin, dept, "mgr@example.com", "manager")
        mgr_id = _id_of(client, mgr)
        before = _version(db_session, mgr_id)

        r = client.put(f"/departments/{dept}/teams/{team_id}/manager/{mgr_id}", headers=auth(admin))
        assert r.status_code == 200, r.text

        assert _version(db_session, mgr_id) == before + 1
        assert _claims(refreshed(client, mgr))["leads"] == [team_id]

    def test_replacing_a_lead_bumps_both_of_them(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        outgoing = invite_user(admin, dept, "out@example.com", "manager")
        incoming = invite_user(admin, dept, "in@example.com", "manager")
        outgoing_id, incoming_id = _id_of(client, outgoing), _id_of(client, incoming)
        client.put(f"/departments/{dept}/teams/{team_id}/manager/{outgoing_id}", headers=auth(admin))
        before = _version(db_session, outgoing_id), _version(db_session, incoming_id)

        client.put(f"/departments/{dept}/teams/{team_id}/manager/{incoming_id}", headers=auth(admin))

        assert (_version(db_session, outgoing_id), _version(db_session, incoming_id)) == (before[0] + 1, before[1] + 1)
        assert _claims(refreshed(client, outgoing))["leads"] == []
        assert _claims(refreshed(client, incoming))["leads"] == [team_id]

    def test_a_demotion_that_hands_the_team_over_bumps_the_replacement_too(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        lead = invite_user(admin, dept, "lead@example.com", "manager")
        heir = invite_user(admin, dept, "heir@example.com", "manager")
        lead_id, heir_id = _id_of(client, lead), _id_of(client, heir)
        client.put(f"/departments/{dept}/teams/{team_id}/manager/{lead_id}", headers=auth(admin))
        before = _version(db_session, heir_id)

        r = client.patch(
            f"/departments/{dept}/members/{lead_id}?replacement_user_id={heir_id}",
            json={"role": "engineer"}, headers=auth(admin),
        )
        assert r.status_code == 200, r.text

        assert _version(db_session, heir_id) == before + 1
        assert _claims(refreshed(client, heir))["leads"] == [team_id]

    def test_joining_and_leaving_a_team_lands_within_seconds(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        assert client.put(f"/departments/{dept}/teams/{team_id}/members/{bob_id}", headers=auth(admin)).status_code == 200
        assert _version(db_session, bob_id) == before + 1
        bob = refreshed(client, bob)
        assert _claims(bob).memberships[0]["team_id"] == team_id

        assert client.delete(f"/departments/{dept}/teams/{team_id}/members/{bob_id}", headers=auth(admin)).status_code == 204
        assert _version(db_session, bob_id) == before + 2
        assert client.get("/me", headers=auth(bob)).status_code == 401
        assert _claims(refreshed(client, bob)).memberships[0]["team_id"] is None

    def test_deleting_a_team_bumps_everyone_it_touched(self, client, db_session, registered_user, invite_user):
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        team_id = _team(client, dept, admin, "Platform")
        lead = invite_user(admin, dept, "lead@example.com", "manager")
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        lead_id, bob_id = _id_of(client, lead), _id_of(client, bob)
        client.put(f"/departments/{dept}/teams/{team_id}/manager/{lead_id}", headers=auth(admin))
        client.put(f"/departments/{dept}/teams/{team_id}/members/{bob_id}", headers=auth(admin))
        before = _version(db_session, lead_id), _version(db_session, bob_id)

        assert client.delete(f"/departments/{dept}/teams/{team_id}", headers=auth(admin)).status_code == 204

        assert (_version(db_session, lead_id), _version(db_session, bob_id)) == (before[0] + 1, before[1] + 1)
        assert _claims(refreshed(client, lead))["leads"] == []
        assert _claims(refreshed(client, bob)).memberships[0]["team_id"] is None

class TestInviteAcceptance:
    def test_an_existing_account_joining_a_second_department_bumps(self, client, db_session, registered_user, invite_user, second_dept):
        admin = registered_user["tokens"]
        bob = invite_user(admin, registered_user["dept_id"], "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        second = invite_user(admin, second_dept, "bob@example.com", "manager")

        assert _version(db_session, bob_id) == before + 1
        # The pair handed back by the accept itself has to survive the bump it caused.
        assert client.get("/me", headers=auth(second)).status_code == 200
        assert client.get("/me", headers=auth(bob)).status_code == 401
        assert {m["dept_id"] for m in _claims(refreshed(client, bob)).memberships} == {registered_user["dept_id"], second_dept}

    def test_a_brand_new_account_is_not_bumped(self, client, db_session, registered_user, invite_user):
        """Nobody is holding a token for an account that did not exist a moment ago, so
        a bump here would be churn for its own sake."""
        bob = invite_user(registered_user["tokens"], registered_user["dept_id"], "bob@example.com", "engineer")
        assert _version(db_session, _id_of(client, bob)) == 0

class TestWhatIsNotABump:
    def test_naming_a_department_head_does_not_bump(self, client, db_session, registered_user, invite_user):
        """head_user_id is not carried in a token, so nothing a product reads changed."""
        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "admin")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)

        assert client.put(f"/departments/{dept}/head/{bob_id}", headers=auth(admin)).status_code == 200

        assert _version(db_session, bob_id) == before
        assert client.get("/me", headers=auth(bob)).status_code == 200

class TestTheHelperItself:
    """Call sites hand it whatever they have — a cleared team lead is None, and a
    concurrent delete leaves an id with no row behind it."""

    def test_it_skips_none_and_unknown_ids_and_bumps_each_person_once(self, client, db_session, registered_user, invite_user, monkeypatch):
        from tests.test_revocations import FakeRedis
        from app.services.auth import bump_token_version

        bob = invite_user(registered_user["tokens"], registered_user["dept_id"], "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        before = _version(db_session, bob_id)
        fake = FakeRedis()
        monkeypatch.setattr(revocations, "_redis", lambda: fake)

        bump_token_version(db_session, None, 999999, bob_id, bob_id)

        assert _version(db_session, bob_id) == before + 1
        assert len(fake.written) == 1

    def test_nothing_to_bump_publishes_nothing(self, db_session, monkeypatch):
        from tests.test_revocations import FakeRedis
        from app.services.auth import bump_token_version

        fake = FakeRedis()
        monkeypatch.setattr(revocations, "_redis", lambda: fake)
        bump_token_version(db_session, None)
        assert fake.written == []

class TestWhatReachesRedis:
    def test_a_membership_change_publishes_the_new_user_version(self, client, db_session, registered_user, invite_user, monkeypatch):
        from tests.test_revocations import FakeRedis

        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "admin")
        bob_id = _id_of(client, bob)
        fake = FakeRedis()
        monkeypatch.setattr(revocations, "_redis", lambda: fake)

        client.patch(f"/departments/{dept}/members/{bob_id}", json={"role": "engineer"}, headers=auth(admin))

        assert fake.written == [(
            f"{revocations.USER_KEY_PREFIX}{bob_id}",
            str(_version(db_session, bob_id)),
            revocations.ttl_seconds(),
        )]

    def test_no_session_marker_is_published(self, client, registered_user, invite_user, monkeypatch):
        """A session marker is what ends a device. Nothing here ends a device."""
        from tests.test_revocations import FakeRedis

        dept, admin = registered_user["dept_id"], registered_user["tokens"]
        bob = invite_user(admin, dept, "bob@example.com", "engineer")
        bob_id = _id_of(client, bob)
        fake = FakeRedis()
        monkeypatch.setattr(revocations, "_redis", lambda: fake)

        client.delete(f"/departments/{dept}/members/{bob_id}", headers=auth(admin))

        assert not [k for k, _, _ in fake.written if k.startswith(revocations.SESSION_KEY_PREFIX)]

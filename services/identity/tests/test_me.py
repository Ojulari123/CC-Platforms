from datetime import datetime
from sqlalchemy import select
from app.models import RefreshToken
from app.security.jwt import decode_access_token

def test_returns_current_user_with_memberships(client, registered_user):
    token = registered_user["tokens"]["access_token"]
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == registered_user["email"]
    assert body["first_name"] == "Alice"
    assert body["email_verified"] is False
    assert body["is_active"] is True
    assert body["is_platform_admin"] is True  # bootstrap user
    assert len(body["memberships"]) == 1
    membership = body["memberships"][0]
    assert membership["role"] == "admin"
    assert membership["dept_name"] == "Engineering"
    assert membership["dept_id"]
    assert membership["team_id"] is None

def test_without_auth_header_401(client):
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"

def test_with_garbage_token_401(client):
    r = client.get("/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401

def test_refresh_token_rejected_on_me(client, registered_user):
    refresh = registered_user["tokens"]["refresh_token"]
    r = client.get("/me", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}

class TestUpdateProfile:
    def test_updates_own_name(self, client, registered_user):
        r = client.patch("/me", json={"first_name": "Alicia"}, headers=_auth(registered_user["tokens"]))
        assert r.status_code == 200
        body = r.json()
        assert body["first_name"] == "Alicia"
        assert body["last_name"] == "Anderson"  # untouched fields stay put

    def test_partial_update_leaves_avatar_alone(self, client, registered_user):
        tokens = registered_user["tokens"]
        client.patch("/me", json={"avatar_url": "https://example.com/a.png"}, headers=_auth(tokens))
        r = client.patch("/me", json={"last_name": "Smith"}, headers=_auth(tokens))
        assert r.json()["avatar_url"] == "https://example.com/a.png"
        assert r.json()["last_name"] == "Smith"

    def test_cannot_change_role_or_email_through_profile(self, client, registered_user):
        tokens = registered_user["tokens"]
        r = client.patch("/me", json={"email": "new@example.com", "active_role": "admin"}, headers=_auth(tokens))
        assert r.status_code == 200
        assert r.json()["email"] == registered_user["email"]  # ignored, not applied

    def test_requires_auth(self, client):
        assert client.patch("/me", json={"first_name": "X"}).status_code == 401

def _parsed(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)

def _login(client, registered_user: dict) -> dict:
    r = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
    assert r.status_code == 200, r.text
    return r.json()

class TestMySessions:
    def test_requires_auth(self, client):
        r = client.get("/me/sessions")
        assert r.status_code == 401
        assert r.json()["detail"] == "Not authenticated"

    def test_refresh_token_rejected(self, client, registered_user):
        refresh = registered_user["tokens"]["refresh_token"]
        assert client.get("/me/sessions", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401

    def test_one_row_per_login(self, client, registered_user):
        second = _login(client, registered_user)
        r = client.get("/me/sessions", headers=_auth(second))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2  # registration issued the first pair, this login the second
        assert [s["rotations"] for s in body] == [0, 0]
        assert all(s["is_revoked"] is False for s in body)
        # REFRESH_TOKEN_EXPIRE_DAYS is 7 in the test env, so expiry is a week out
        assert all((_parsed(s["expires_at"]) - _parsed(s["started_at"])).days == 7 for s in body)

    def test_only_the_callers_own_sessions(self, client, registered_user, engineer_user):
        mine = client.get("/me/sessions", headers=_auth(registered_user["tokens"])).json()
        theirs = client.get("/me/sessions", headers=_auth(engineer_user)).json()
        assert len(mine) == 1
        assert len(theirs) == 1
        assert {s["session_id"] for s in mine}.isdisjoint({s["session_id"] for s in theirs})

    def test_marks_the_calling_session(self, client, registered_user):
        second = _login(client, registered_user)
        body = client.get("/me/sessions", headers=_auth(second)).json()
        current = [s for s in body if s["is_current"]]
        assert len(current) == 1
        assert current[0]["session_id"] == decode_access_token(second["access_token"]).session_id

    def test_rotation_stays_one_session(self, client, registered_user):
        tokens = _login(client, registered_user)
        rotated = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
        body = client.get("/me/sessions", headers=_auth(rotated)).json()
        assert len(body) == 2  # rotation replaced the token, not the session
        current = [s for s in body if s["is_current"]][0]
        assert current["rotations"] == 1
        assert current["is_revoked"] is False
        assert current["session_id"] == decode_access_token(tokens["access_token"]).session_id

    def test_revoked_family_reads_as_revoked(self, client, registered_user):
        doomed = _login(client, registered_user)
        keeper = _login(client, registered_user)
        assert client.post("/auth/logout", json={"refresh_token": doomed["refresh_token"]}).status_code == 204
        body = client.get("/me/sessions", headers=_auth(keeper)).json()
        revoked = [s for s in body if s["is_revoked"]]
        assert len(revoked) == 1
        assert revoked[0]["session_id"] == decode_access_token(doomed["access_token"]).session_id
        assert revoked[0]["is_current"] is False

    def test_logout_all_revokes_every_row(self, client, registered_user):
        _login(client, registered_user)
        tokens = _login(client, registered_user)
        assert client.post("/auth/logout-all", headers=_auth(tokens)).status_code == 204
        fresh = _login(client, registered_user)
        body = client.get("/me/sessions", headers=_auth(fresh)).json()
        assert sum(1 for s in body if s["is_revoked"]) == 3
        assert [s["is_revoked"] for s in body if s["is_current"]] == [False]

    def test_end_one_session_leaves_the_others_alone(self, client, registered_user):
        doomed = _login(client, registered_user)
        keeper = _login(client, registered_user)
        doomed_id = decode_access_token(doomed["access_token"]).session_id

        assert client.delete(f"/me/sessions/{doomed_id}", headers=_auth(keeper)).status_code == 204

        assert client.post("/auth/refresh", json={"refresh_token": doomed["refresh_token"]}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": keeper["refresh_token"]}).status_code == 200
        assert client.get("/me", headers=_auth(registered_user["tokens"])).status_code == 200

        body = client.get("/me/sessions", headers=_auth(keeper)).json()
        assert [s["is_revoked"] for s in body if s["session_id"] == doomed_id] == [True]
        assert sum(1 for s in body if s["is_revoked"]) == 1

    def test_end_one_session_does_not_bump_token_version(self, client, registered_user, db_session):
        from app.models import User

        doomed = _login(client, registered_user)
        user_id = client.get("/me", headers=_auth(doomed)).json()["id"]
        before = db_session.get(User, user_id).token_version

        session_id = decode_access_token(doomed["access_token"]).session_id
        assert client.delete(f"/me/sessions/{session_id}", headers=_auth(doomed)).status_code == 204

        db_session.expire_all()
        assert db_session.get(User, user_id).token_version == before
        # The access token from the killed family is deliberately still good until it
        # expires; only minting new ones has stopped.
        assert client.get("/me", headers=_auth(doomed)).status_code == 200

    def test_end_current_session_uses_the_sid_claim(self, client, registered_user):
        mine = _login(client, registered_user)
        other = _login(client, registered_user)
        assert client.delete("/me/sessions/current", headers=_auth(mine)).status_code == 204

        assert client.post("/auth/refresh", json={"refresh_token": mine["refresh_token"]}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 200

        current = [s for s in client.get("/me/sessions", headers=_auth(mine)).json() if s["is_current"]]
        assert [s["is_revoked"] for s in current] == [True]

    def test_ending_the_same_session_twice_is_idempotent(self, client, registered_user):
        doomed = _login(client, registered_user)
        keeper = _login(client, registered_user)
        session_id = decode_access_token(doomed["access_token"]).session_id
        assert client.delete(f"/me/sessions/{session_id}", headers=_auth(keeper)).status_code == 204
        assert client.delete(f"/me/sessions/{session_id}", headers=_auth(keeper)).status_code == 204

    def test_unknown_session_id_is_404_not_500(self, client, registered_user):
        for unknown in ("0" * 32, "not-a-session-id", "1' OR '1'='1", "x" * 500):
            r = client.delete(f"/me/sessions/{unknown}", headers=_auth(registered_user["tokens"]))
            assert r.status_code == 404, unknown
            assert r.json()["detail"] == "Session not found", unknown
        # A value the router cannot match at all is still a 404, just Starlette's own.
        assert client.delete("/me/sessions/%2e%2e%2fetc%2fpasswd", headers=_auth(registered_user["tokens"])).status_code == 404

    def test_cannot_end_another_users_session(self, client, registered_user, engineer_user):
        theirs = client.get("/me/sessions", headers=_auth(engineer_user)).json()[0]["session_id"]
        # 404, not 403: the caller is only ever shown their own sessions, and confirming
        # this id exists would say it belongs to someone.
        r = client.delete(f"/me/sessions/{theirs}", headers=_auth(registered_user["tokens"]))
        assert r.status_code == 404

        # and it still works
        assert client.get("/me/sessions", headers=_auth(engineer_user)).json()[0]["is_revoked"] is False

    def test_ending_a_session_requires_auth(self, client, registered_user):
        session_id = client.get("/me/sessions", headers=_auth(registered_user["tokens"])).json()[0]["session_id"]
        assert client.delete(f"/me/sessions/{session_id}").status_code == 401
        assert client.delete("/me/sessions/current").status_code == 401
        assert client.get("/me/sessions", headers=_auth(registered_user["tokens"])).json()[0]["is_revoked"] is False

    def test_refresh_token_cannot_end_a_session(self, client, registered_user):
        headers = {"Authorization": f"Bearer {registered_user['tokens']['refresh_token']}"}
        assert client.delete("/me/sessions/current", headers=headers).status_code == 401

    def test_logout_all_still_ends_everything(self, client, registered_user):
        first = _login(client, registered_user)
        second = _login(client, registered_user)
        assert client.delete("/me/sessions/current", headers=_auth(first)).status_code == 204
        assert client.post("/auth/logout-all", headers=_auth(second)).status_code == 204

        assert client.get("/me", headers=_auth(second)).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
        fresh = _login(client, registered_user)
        assert all(s["is_revoked"] for s in client.get("/me/sessions", headers=_auth(fresh)).json() if not s["is_current"])

    def test_ending_a_session_returns_no_body(self, client, registered_user):
        doomed = _login(client, registered_user)
        r = client.delete("/me/sessions/current", headers=_auth(doomed))
        assert r.status_code == 204
        assert r.content == b""

    def test_no_token_material_in_the_response(self, client, registered_user, db_session):
        tokens = _login(client, registered_user)
        client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        r = client.get("/me/sessions", headers=_auth(registered_user["tokens"]))
        raw = r.text

        stored = db_session.scalars(select(RefreshToken)).all()
        assert len(stored) == 3
        for row in stored:
            assert row.token_hash not in raw
            assert row.family_id not in raw
        for secret in (tokens["refresh_token"], tokens["access_token"], registered_user["tokens"]["refresh_token"]):
            assert secret not in raw

        keys = set().union(*(s.keys() for s in r.json()))
        assert keys == {"session_id", "started_at", "last_used_at", "rotations", "expires_at", "is_revoked", "is_current"}

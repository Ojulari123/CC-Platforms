from sqlalchemy import select

from app.config import settings
from app.models import User
from app.security.jwt import create_access_token, create_service_token, decode_access_token
from tests.conftest import auth


def _login(client, user):
    return client.post("/auth/login", json={"email": user["email"], "password": user["password"]})


class TestAccessTokenRejected:
    def test_expired_access_token_is_401(self, client, registered_user, monkeypatch):
        monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
        login = _login(client, registered_user)
        assert login.status_code == 200, login.text
        r = client.get("/me", headers=auth(login.json()))
        assert r.status_code == 401
        assert "expired" in r.json()["detail"].lower()

    def test_service_token_cannot_stand_in_for_a_person(self, client, registered_user):
        token = create_service_token(client_id="pulse", scopes="users:read:email")
        r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Wrong token type"

    def test_token_for_a_user_that_does_not_exist_is_401(self, client, registered_user):
        ghost = create_access_token(
            user_id=999999, email="ghost@example.com", memberships=[],
            is_platform_admin=False, token_version=0,
        )
        r = client.get("/me", headers={"Authorization": f"Bearer {ghost}"})
        assert r.status_code == 401
        assert r.json()["detail"] == "User not found"


class TestTokenClaims:
    def test_claims_survive_a_round_trip(self):
        token = create_access_token(
            user_id=7,
            email="ada@example.com",
            memberships=[
                {"dept_id": 1, "team_id": None, "role": "admin"},
                {"dept_id": 2, "team_id": 5, "role": "engineer"},
            ],
            is_platform_admin=True,
            token_version=3,
            leads=[5],
        )
        payload = decode_access_token(token)
        assert payload.user_id == 7
        assert payload.token_version == 3
        assert payload.is_platform_admin is True
        assert payload.leads == [5]
        assert len(payload.memberships) == 2

    def test_role_in_picks_the_right_department(self):
        token = create_access_token(
            user_id=7,
            email="ada@example.com",
            memberships=[
                {"dept_id": 1, "team_id": None, "role": "admin"},
                {"dept_id": 2, "team_id": 5, "role": "engineer"},
            ],
            is_platform_admin=False,
            token_version=0,
        )
        payload = decode_access_token(token)
        assert payload.role_in(1) == "admin"
        assert payload.role_in(2) == "engineer"
        assert payload.role_in(99) is None

    def test_absent_optional_claims_default_safely(self):
        token = create_access_token(
            user_id=7, email="ada@example.com", memberships=[],
            is_platform_admin=False, token_version=0,
        )
        payload = decode_access_token(token)
        assert payload.is_platform_admin is False
        assert payload.memberships == []
        assert payload.leads == []


class TestRefreshTokenGuards:
    def test_expired_refresh_token_is_401_and_burned(self, client, registered_user, monkeypatch):
        monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", -1)
        login = _login(client, registered_user)
        refresh = login.json()["refresh_token"]

        r = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 401
        assert "expired" in r.json()["detail"].lower()

        # It was revoked on the way out, so a second attempt lands in the dead-family
        # branch rather than the expiry one. It was burned, never rotated away, so this
        # is not a theft signal and the account is left alone — it used to read as
        # reuse and sign the person out of every other device.
        again = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert again.status_code == 401
        assert again.json()["detail"] == "Session ended. Please log in again."
        assert client.get("/me", headers=auth(registered_user["tokens"])).status_code == 200

    def test_deactivated_user_cannot_refresh(self, client, registered_user, engineer_user, db_session):
        user = db_session.scalar(select(User).where(User.email == "eng@example.com"))
        user.is_active = False
        db_session.commit()

        r = client.post("/auth/refresh", json={"refresh_token": engineer_user["refresh_token"]})
        assert r.status_code == 401
        assert r.json()["detail"] == "User not available"


class TestTeamManagerGuard:
    def _team(self, client, tokens, dept_id, name="Platform"):
        r = client.post(f"/departments/{dept_id}/teams", json={"name": name}, headers=auth(tokens))
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_member_of_another_department_is_refused(self, client, registered_user, engineer_user, invite_user, second_dept):
        dept = registered_user["dept_id"]
        team_id = self._team(client, registered_user["tokens"], dept)
        outsider = invite_user(registered_user["tokens"], second_dept, "data@example.com", "engineer")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(outsider))
        assert r.status_code == 403
        assert r.json()["detail"] == "Not a member of this department"

    def test_department_admin_may_manage_a_team_they_do_not_lead(self, client, registered_user, engineer_user, invite_user):
        dept = registered_user["dept_id"]
        team_id = self._team(client, registered_user["tokens"], dept)
        other_admin = invite_user(registered_user["tokens"], dept, "admin2@example.com", "admin")
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]

        r = client.put(f"/departments/{dept}/teams/{team_id}/members/{eng_id}", headers=auth(other_admin))
        assert r.status_code == 200, r.text
        assert r.json()["team_id"] == team_id


class TestPasswordResetGuards:
    def test_deactivated_account_cannot_complete_a_reset(self, client, registered_user, engineer_user, db_session, monkeypatch):
        from app.services import email as email_service

        captured = []
        monkeypatch.setattr(email_service, "is_configured", lambda: True)
        monkeypatch.setattr(
            email_service, "send_password_reset",
            lambda to, raw_token: captured.append(raw_token),
        )
        assert client.post("/auth/forgot-password", json={"email": "eng@example.com"}).status_code == 204

        user = db_session.scalar(select(User).where(User.email == "eng@example.com"))
        user.is_active = False
        db_session.commit()

        r = client.post("/auth/reset-password", json={"token": captured[0], "new_password": "NewPass123!"})
        assert r.status_code == 400

    def test_a_failed_send_still_looks_like_success(self, client, registered_user, monkeypatch):
        from app.services import email as email_service

        def boom(to, raw_token):
            raise email_service.EmailSendError("smtp down")

        monkeypatch.setattr(email_service, "is_configured", lambda: True)
        monkeypatch.setattr(email_service, "send_password_reset", boom)

        r = client.post("/auth/forgot-password", json={"email": registered_user["email"]})
        assert r.status_code == 204


class TestInviteGuards:
    def test_expired_invite_cannot_be_accepted(self, client, registered_user, sent_emails, monkeypatch):
        monkeypatch.setattr(settings, "INVITE_EXPIRE_DAYS", -1)
        r = client.post(
            f"/departments/{registered_user['dept_id']}/invites",
            json={"email": "late@example.com", "role": "engineer", "team_id": None},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text

        accept = client.post("/invites/accept", json={
            "token": sent_emails[-1]["raw_token"],
            "first_name": "Late",
            "last_name": "Tester",
            "password": "Test123!password",
        })
        assert accept.status_code == 400
        assert "expired" in accept.json()["detail"].lower()

    def test_deactivated_account_cannot_accept_an_invite(self, client, registered_user, sent_emails, db_session):
        signup = client.post("/auth/signup", json={
            "email": "drifter@example.com",
            "password": "Test123!password",
            "first_name": "Drifter",
            "last_name": "Tester",
        })
        assert signup.status_code == 201, signup.text
        user_id = client.get("/me", headers=auth(signup.json())).json()["id"]

        r = client.post(
            f"/departments/{registered_user['dept_id']}/invites",
            json={"email": "drifter@example.com", "role": "engineer", "team_id": None},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text

        assert client.post(f"/platform/users/{user_id}/deactivate", headers=auth(registered_user["tokens"])).status_code == 200

        accept = client.post("/invites/accept", json={"token": sent_emails[-1]["raw_token"]})
        assert accept.status_code == 403
        assert "deactivated" in accept.json()["detail"].lower()


class TestPlatformAdminGrant:
    def test_a_deactivated_account_cannot_be_promoted(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        assert client.post(f"/platform/users/{eng_id}/deactivate", headers=auth(registered_user["tokens"])).status_code == 200

        r = client.put(f"/platform/admins/{eng_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "deactivated" in r.json()["detail"].lower()

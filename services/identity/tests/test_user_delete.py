from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from app.models import Invite, PasswordResetToken, RefreshToken, Team, User
from tests.conftest import auth

def _signup(client, email="typo@example.com", first="Typo", last="Account"):
    r = client.post("/auth/signup", json={
        "email": email, "password": "Test123!password", "first_name": first, "last_name": last,
    })
    assert r.status_code == 201, r.text
    return r.json()

def _delete(client, tokens, user_id):
    return client.delete(f"/platform/users/{user_id}", headers=auth(tokens))

def _id_of(client, tokens):
    return client.get("/me", headers=auth(tokens)).json()["id"]

class TestDeleteAnUnusedAccount:
    def test_a_never_used_signup_is_removed(self, client, registered_user):
        stray = _signup(client)
        stray_id = _id_of(client, stray)

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204

        directory = client.get("/platform/users", headers=auth(registered_user["tokens"])).json()
        assert "typo@example.com" not in {u["email"] for u in directory["items"]}

    def test_their_token_stops_working(self, client, registered_user):
        stray = _signup(client)
        _delete(client, registered_user["tokens"], _id_of(client, stray))
        assert client.get("/me", headers=auth(stray)).status_code == 401

    def test_they_cannot_log_in_afterwards(self, client, registered_user):
        stray = _signup(client)
        _delete(client, registered_user["tokens"], _id_of(client, stray))
        r = client.post("/auth/login", json={"email": "typo@example.com", "password": "Test123!password"})
        assert r.status_code == 401

class TestDeleteCleansUp:
    def test_refresh_tokens_go(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        assert db_session.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == stray_id)) == 1

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204
        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == stray_id)) == 0

    def test_password_reset_tokens_go(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.add(PasswordResetToken(
            user_id=stray_id, token_hash="a" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        db_session.commit()

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204
        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(PasswordResetToken).where(PasswordResetToken.user_id == stray_id)) == 0

    def test_an_invite_they_sent_survives_without_an_inviter(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.add(Invite(
            dept_id=registered_user["dept_id"], email="pending@example.com", role="engineer",
            token_hash="b" * 64, invited_by=stray_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
        db_session.commit()

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204
        db_session.expire_all()
        invite = db_session.scalar(select(Invite).where(Invite.email == "pending@example.com"))
        assert invite is not None
        assert invite.invited_by is None

    def test_the_user_row_itself_is_gone(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        _delete(client, registered_user["tokens"], stray_id)
        db_session.expire_all()
        assert db_session.get(User, stray_id) is None

class TestDeleteIsRefused:
    def test_a_department_member_is_refused(self, client, registered_user, engineer_user):
        eng_id = _id_of(client, engineer_user)
        r = _delete(client, registered_user["tokens"], eng_id)
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "belongs to 1 department(s)" in detail
        assert "Deactivate it instead" in detail

    def test_an_ex_member_is_still_refused_after_removal(self, client, registered_user, invite_user, db_session):
        dept = registered_user["dept_id"]
        leaver = invite_user(registered_user["tokens"], dept, "leaver@example.com", "engineer")
        leaver_id = _id_of(client, leaver)
        assert client.delete(f"/departments/{dept}/members/{leaver_id}", headers=auth(registered_user["tokens"])).status_code == 204
        db_session.expire_all()
        assert db_session.get(User, leaver_id).onboarded_at is not None

        r = _delete(client, registered_user["tokens"], leaver_id)
        assert r.status_code == 400
        assert "they have been part of a department" in r.json()["detail"]
        assert "Deactivate it instead" in r.json()["detail"]

    def test_an_ex_member_stays_refused_even_with_no_other_trace(self, client, registered_user, invite_user, db_session):
        dept = registered_user["dept_id"]
        leaver = invite_user(registered_user["tokens"], dept, "leaver@example.com", "engineer")
        leaver_id = _id_of(client, leaver)
        assert client.delete(f"/departments/{dept}/members/{leaver_id}", headers=auth(registered_user["tokens"])).status_code == 204
        db_session.expire_all()
        user = db_session.get(User, leaver_id)
        user.token_version = 0
        user.email_verified = False
        db_session.query(Invite).filter(Invite.email == "leaver@example.com").delete(synchronize_session=False)
        db_session.commit()

        r = _delete(client, registered_user["tokens"], leaver_id)
        assert r.status_code == 400
        assert "they have been part of a department" in r.json()["detail"]

    def test_an_invite_accepter_is_refused(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.get(User, stray_id).email_verified = True
        db_session.commit()

        r = _delete(client, registered_user["tokens"], stray_id)
        assert r.status_code == 400
        assert "accepting an emailed invite" in r.json()["detail"]

    def test_an_accepted_invite_row_refuses_it(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.add(Invite(
            dept_id=registered_user["dept_id"], email="typo@example.com", role="engineer",
            token_hash="c" * 64, invited_by=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            accepted_at=datetime.now(timezone.utc),
        ))
        db_session.commit()

        r = _delete(client, registered_user["tokens"], stray_id)
        assert r.status_code == 400
        assert "accepted a department invite before" in r.json()["detail"]

    def test_a_team_lead_is_refused(self, client, registered_user, db_session):
        dept = registered_user["dept_id"]
        team_id = client.post(f"/departments/{dept}/teams", json={"name": "Platform"}, headers=auth(registered_user["tokens"])).json()["id"]
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.get(Team, team_id).manager_user_id = stray_id
        db_session.commit()

        r = _delete(client, registered_user["tokens"], stray_id)
        assert r.status_code == 400
        assert "still leads Platform" in r.json()["detail"]

    def test_a_department_head_is_refused(self, client, registered_user, db_session):
        from app.models import Department
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.get(Department, registered_user["dept_id"]).head_user_id = stray_id
        db_session.commit()

        r = _delete(client, registered_user["tokens"], stray_id)
        assert r.status_code == 400
        assert "still heads Engineering" in r.json()["detail"]

    def test_a_platform_admin_is_refused(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        db_session.get(User, stray_id).is_platform_admin = True
        db_session.commit()

        r = _delete(client, registered_user["tokens"], stray_id)
        assert r.status_code == 400
        assert "revoke their platform admin role first" in r.json()["detail"]

    def test_the_last_platform_admin_cannot_be_demoted_then_deleted(self, client, registered_user):
        me_id = _id_of(client, registered_user["tokens"])
        r = client.delete(f"/platform/admins/{me_id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "only platform administrator" in r.json()["detail"]

    def test_you_cannot_delete_yourself(self, client, registered_user):
        me_id = _id_of(client, registered_user["tokens"])
        r = _delete(client, registered_user["tokens"], me_id)
        assert r.status_code == 400
        assert "your own account" in r.json()["detail"]

    def test_an_engineer_cannot_delete_anyone(self, client, registered_user, engineer_user):
        stray = _signup(client)
        r = _delete(client, engineer_user, _id_of(client, stray))
        assert r.status_code == 403
        assert "platform administrator" in r.json()["detail"]

    def test_unknown_user_is_404(self, client, registered_user):
        r = _delete(client, registered_user["tokens"], 9999)
        assert r.status_code == 404
        assert r.json()["detail"] == "User not found"

class TestOnboardedAtIsStampedEverywhere:
    def test_the_bootstrap_registration_stamps_it(self, client, registered_user, db_session):
        assert db_session.get(User, _id_of(client, registered_user["tokens"])).onboarded_at is not None

    def test_accepting_an_invite_stamps_it(self, client, registered_user, invite_user, db_session):
        joiner = invite_user(registered_user["tokens"], registered_user["dept_id"], "joiner@example.com", "engineer")
        assert db_session.get(User, _id_of(client, joiner)).onboarded_at is not None

    def test_adding_a_member_directly_stamps_it(self, client, registered_user, db_session):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        assert db_session.get(User, stray_id).onboarded_at is None

        r = client.post(
            f"/departments/{registered_user['dept_id']}/members",
            json={"user_id": stray_id, "role": "engineer"},
            headers=auth(registered_user["tokens"]),
        )
        assert r.status_code == 201, r.text
        db_session.expire_all()
        assert db_session.get(User, stray_id).onboarded_at is not None

    def test_a_second_membership_does_not_move_the_stamp(self, client, registered_user, second_dept, invite_user, db_session):
        joiner = invite_user(registered_user["tokens"], registered_user["dept_id"], "joiner@example.com", "engineer")
        joiner_id = _id_of(client, joiner)
        db_session.expire_all()
        first = db_session.get(User, joiner_id).onboarded_at

        r = client.post(f"/departments/{second_dept}/members",
                        json={"user_id": joiner_id, "role": "engineer"},
                        headers=auth(registered_user["tokens"]))
        assert r.status_code == 201, r.text
        db_session.expire_all()
        assert db_session.get(User, joiner_id).onboarded_at == first

class TestDeleteIsAllowedForNeverOnboardedAccounts:
    def test_changing_a_password_no_longer_blocks_deletion(self, client, registered_user):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        r = client.post("/auth/change-password", headers=auth(stray), json={
            "current_password": "Test123!password", "new_password": "Test456!password",
        })
        assert r.status_code == 200, r.text

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204

    def test_signing_out_everywhere_no_longer_blocks_deletion(self, client, registered_user):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        assert client.post("/auth/logout-all", headers=auth(stray)).status_code == 204

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204

    def test_a_deactivated_never_onboarded_account_is_still_deletable(self, client, registered_user):
        stray = _signup(client)
        stray_id = _id_of(client, stray)
        assert client.post(f"/platform/users/{stray_id}/deactivate", headers=auth(registered_user["tokens"])).status_code == 200

        assert _delete(client, registered_user["tokens"], stray_id).status_code == 204

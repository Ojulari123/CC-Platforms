"""Migration 0010's backfill, run against pre-migration rows. The chain itself can't
run here (0003 is Postgres-only), so the UPDATE is imported from the migration and
run as-is — fresh rows carry onboarded_at=NULL, which is the pre-migration state."""
import importlib.util
from pathlib import Path
from sqlalchemy import text
from app.models import Membership, User
from tests.conftest import auth

_spec = importlib.util.spec_from_file_location(
    "migration_0010",
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0010_user_onboarded_at.py",
)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

def _user(db, email, **kwargs):
    user = User(email=email, password_hash="x", first_name="Pre", last_name="Migration", **kwargs)
    db.add(user)
    db.flush()
    return user

def _run_backfill(db):
    db.execute(text(_migration._BACKFILL))
    db.commit()

class TestBackfill:
    def test_an_ex_member_is_stamped_even_with_no_membership_row(self, db_session):
        """The one that matters. remove_member hard-deletes the membership, so a
        membership-only backfill would leave a two-year employee NULL and hand
        the delete endpoint permission to erase them."""
        leaver = _user(db_session, "leaver@example.com", token_version=3)
        db_session.commit()
        assert db_session.scalar(text("SELECT COUNT(*) FROM memberships WHERE user_id = :i"), {"i": leaver.id}) == 0

        _run_backfill(db_session)
        db_session.refresh(leaver)
        assert leaver.onboarded_at is not None

    def test_a_current_member_is_stamped(self, db_session, registered_user):
        dept_id = registered_user["dept_id"]
        member = _user(db_session, "current@example.com")
        db_session.add(Membership(user_id=member.id, dept_id=dept_id, role="engineer"))
        db_session.commit()

        _run_backfill(db_session)
        db_session.refresh(member)
        assert member.onboarded_at is not None

    def test_a_verified_account_is_stamped(self, db_session):
        """email_verified is only ever set by accepting an invite, and the old
        rule refused on it — so it must not become deletable here either."""
        verified = _user(db_session, "verified@example.com", email_verified=True)
        db_session.commit()

        _run_backfill(db_session)
        db_session.refresh(verified)
        assert verified.onboarded_at is not None

    def test_a_pristine_account_is_left_alone(self, db_session):
        pristine = _user(db_session, "pristine@example.com")
        db_session.commit()

        _run_backfill(db_session)
        db_session.refresh(pristine)
        assert pristine.onboarded_at is None

    def test_an_existing_stamp_is_not_overwritten(self, db_session, registered_user, client):
        alice_id = client.get("/me", headers=auth(registered_user["tokens"])).json()["id"]
        before = db_session.get(User, alice_id).onboarded_at
        assert before is not None

        _run_backfill(db_session)
        db_session.expire_all()
        assert db_session.get(User, alice_id).onboarded_at == before

class TestBackfillDecidesDeletability:
    """Same rows, run through the real endpoint afterwards — the backfill is only
    correct if it produces the same refusals the old rule gave."""

    def test_the_ex_member_still_cannot_be_deleted(self, client, db_session, registered_user):
        leaver = _user(db_session, "leaver@example.com", token_version=3)
        db_session.commit()
        _run_backfill(db_session)

        r = client.delete(f"/platform/users/{leaver.id}", headers=auth(registered_user["tokens"]))
        assert r.status_code == 400
        assert "they have been part of a department" in r.json()["detail"]

    def test_the_pristine_account_can_be_deleted(self, client, db_session, registered_user):
        pristine = _user(db_session, "pristine@example.com")
        db_session.commit()
        _run_backfill(db_session)

        assert client.delete(f"/platform/users/{pristine.id}", headers=auth(registered_user["tokens"])).status_code == 204

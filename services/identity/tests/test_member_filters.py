from contextlib import contextmanager
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.models import Membership
from tests.conftest import auth

def _create_team(client, tokens, dept_id, name="Platform"):
    r = client.post(f"/departments/{dept_id}/teams", json={"name": name}, headers=auth(tokens))
    assert r.status_code == 201, r.text
    return r.json()["id"]

def _members(client, tokens, dept_id, **params):
    return client.get(f"/departments/{dept_id}/members", params=params, headers=auth(tokens))

@contextmanager
def _statements():
    seen = []

    def _record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

class TestMemberFilters:
    def test_filter_by_role(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        invite_user(tokens, dept, "eng1@example.com", "engineer")
        invite_user(tokens, dept, "eng2@example.com", "engineer")
        invite_user(tokens, dept, "mgr@example.com", "manager")

        body = _members(client, tokens, dept, role="engineer").json()
        assert body["total"] == 2
        assert {m["email"] for m in body["items"]} == {"eng1@example.com", "eng2@example.com"}

    def test_filter_by_team(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        team = _create_team(client, tokens, dept)
        invite_user(tokens, dept, "onteam@example.com", "engineer", team_id=team)
        invite_user(tokens, dept, "offteam@example.com", "engineer")

        body = _members(client, tokens, dept, team_id=team).json()
        assert body["total"] == 1
        assert body["items"][0]["email"] == "onteam@example.com"

    def test_search_matches_email_and_name(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        invite_user(tokens, dept, "findme@example.com", "engineer")
        invite_user(tokens, dept, "other@example.com", "engineer")

        by_email = _members(client, tokens, dept, q="findme").json()
        assert by_email["total"] == 1
        assert by_email["items"][0]["email"] == "findme@example.com"

        # invite_user sets last_name="Tester" on everyone it creates; alice is
        # "Anderson", so this matches the two invitees and not the admin.
        by_last_name = _members(client, tokens, dept, q="tester").json()
        assert by_last_name["total"] == 2

    def test_total_reflects_the_filter_not_the_page(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        for i in range(3):
            invite_user(tokens, dept, f"eng{i}@example.com", "engineer")

        body = _members(client, tokens, dept, role="engineer", limit=2).json()
        assert body["total"] == 3        # every engineer, filtered
        assert len(body["items"]) == 2   # one page of them
        assert body["limit"] == 2

    def test_unknown_role_value_is_rejected(self, client, registered_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        assert _members(client, tokens, dept, role="wizard").status_code == 422

class TestMembershipHasNoActiveFlag:
    """A membership is either there or deleted. The old is_active column claimed a
    middle state nothing ever wrote, so every filter on it was permanently true. The
    field that survives it reports the ACCOUNT's status."""

    def test_the_column_is_gone(self):
        assert "is_active" not in Membership.__table__.columns

    def test_a_member_is_reported_with_the_account_status(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        invite_user(tokens, dept, "eng@example.com", "engineer")

        item = _members(client, tokens, dept, q="eng@example.com").json()["items"][0]
        assert set(item) == {"user_id", "email", "first_name", "last_name", "role", "team_id", "is_active"}
        assert item["is_active"] is True

    def test_a_team_roster_is_reported_with_the_account_status(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        team = _create_team(client, tokens, dept, "Rosters")
        invite_user(tokens, dept, "onteam@example.com", "engineer", team_id=team)

        r = client.get(f"/departments/{dept}/teams/{team}/members", headers=auth(tokens))
        assert r.status_code == 200, r.text
        assert set(r.json()[0]) == {"user_id", "email", "first_name", "last_name", "role", "team_id", "is_active"}
        assert r.json()[0]["is_active"] is True

    def test_a_deactivated_account_still_shows_on_the_roster(self, client, registered_user, engineer_user):
        """Deactivating an ACCOUNT is a separate thing from department membership,
        and always was — the roster filters never looked at it. Proves dropping
        the membership flag didn't quietly wire the two together."""
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        user_id = engineer_user["user"]["id"]
        assert client.post(f"/platform/users/{user_id}/deactivate", headers=auth(tokens)).status_code == 200

        emails = {m["email"] for m in _members(client, tokens, dept).json()["items"]}
        assert "eng@example.com" in emails

class TestMemberActiveStatusComesFromTheAccount:
    def test_a_deactivated_member_reads_as_inactive(self, client, registered_user, engineer_user):
        """They stay on the roster, marked — a department admin has to be able to
        see who can no longer log in."""
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        user_id = engineer_user["user"]["id"]
        client.post(f"/platform/users/{user_id}/deactivate", headers=auth(tokens))

        by_email = {m["email"]: m for m in _members(client, tokens, dept).json()["items"]}
        assert by_email["eng@example.com"]["is_active"] is False
        assert by_email["alice@example.com"]["is_active"] is True

    def test_a_deactivated_member_reads_as_inactive_on_a_team_roster(self, client, registered_user, invite_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        team = _create_team(client, tokens, dept, "Statuses")
        member = invite_user(tokens, dept, "onteam@example.com", "engineer", team_id=team)
        client.post(f"/platform/users/{member['user']['id']}/deactivate", headers=auth(tokens))

        roster = client.get(f"/departments/{dept}/teams/{team}/members", headers=auth(tokens)).json()
        assert [m["is_active"] for m in roster] == [False]

    def test_reactivating_puts_them_back(self, client, registered_user, engineer_user):
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        user_id = engineer_user["user"]["id"]
        client.post(f"/platform/users/{user_id}/deactivate", headers=auth(tokens))
        client.post(f"/platform/users/{user_id}/reactivate", headers=auth(tokens))

        by_email = {m["email"]: m for m in _members(client, tokens, dept).json()["items"]}
        assert by_email["eng@example.com"]["is_active"] is True

    def test_the_roster_costs_the_same_however_many_members(self, client, registered_user, invite_user):
        """The status comes off the join the roster already does. If it ever
        turned into a lookup per row this count would grow with the roster."""
        tokens, dept = registered_user["tokens"], registered_user["dept_id"]
        invite_user(tokens, dept, "eng1@example.com", "engineer")

        with _statements() as small:
            assert len(_members(client, tokens, dept).json()["items"]) == 2

        for i in range(2, 6):
            invite_user(tokens, dept, f"eng{i}@example.com", "engineer")

        with _statements() as large:
            assert len(_members(client, tokens, dept).json()["items"]) == 6

        assert len(large) == len(small)

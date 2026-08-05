from tests.conftest import auth

def _create_team(client, tokens, dept_id, name="Platform"):
    r = client.post(f"/departments/{dept_id}/teams", json={"name": name}, headers=auth(tokens))
    assert r.status_code == 201, r.text
    return r.json()["id"]

def _members(client, tokens, dept_id, **params):
    return client.get(f"/departments/{dept_id}/members", params=params, headers=auth(tokens))

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

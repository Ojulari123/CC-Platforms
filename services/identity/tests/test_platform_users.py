from app.models import User
from tests.conftest import auth

def _list(client, tokens, **params):
    return client.get("/platform/users", headers=auth(tokens), params=params)

class TestPlatformUserList:
    def test_platform_admin_sees_every_user_regardless_of_department(
        self, client, registered_user, second_dept, invite_user, db_session
    ):
        """The flat directory spans departments — not just the caller's own."""
        invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")
        invite_user(registered_user["tokens"], second_dept, "dana@example.com", "engineer")
        # A user with no department at all still shows up — this list isn't a roster.
        db_session.add(User(
            email="loner@example.com", password_hash="x",
            first_name="Loner", last_name="Nobody",
        ))
        db_session.commit()

        body = _list(client, registered_user["tokens"]).json()
        emails = {u["email"] for u in body["items"]}
        assert emails == {"alice@example.com", "eng@example.com", "dana@example.com", "loner@example.com"}
        assert body["total"] == 4

    def test_non_platform_admin_is_forbidden(self, client, registered_user, engineer_user):
        r = _list(client, engineer_user)
        assert r.status_code == 403
        assert "platform administrator" in r.json()["detail"]

    def test_q_matches_by_email(self, client, registered_user, engineer_user):
        body = _list(client, registered_user["tokens"], q="eng@").json()
        assert [u["email"] for u in body["items"]] == ["eng@example.com"]
        assert body["total"] == 1

    def test_q_matches_by_name(self, client, registered_user, engineer_user):
        body = _list(client, registered_user["tokens"], q="alice").json()
        assert [u["email"] for u in body["items"]] == ["alice@example.com"]
        assert body["total"] == 1

    def test_is_active_false_returns_only_deactivated(self, client, registered_user, engineer_user):
        eng_id = client.get("/me", headers=auth(engineer_user)).json()["id"]
        client.post(f"/platform/users/{eng_id}/deactivate", headers=auth(registered_user["tokens"]))

        body = _list(client, registered_user["tokens"], is_active=False).json()
        assert [u["email"] for u in body["items"]] == ["eng@example.com"]
        assert body["items"][0]["is_active"] is False
        assert body["total"] == 1

    def test_pagination_slices_and_total_reflects_full_count(
        self, client, registered_user, second_dept, invite_user
    ):
        invite_user(registered_user["tokens"], registered_user["dept_id"], "eng@example.com", "engineer")
        invite_user(registered_user["tokens"], second_dept, "dana@example.com", "engineer")

        page = _list(client, registered_user["tokens"], limit=2, offset=0).json()
        assert len(page["items"]) == 2
        assert page["total"] == 3  # total ignores the page window

        rest = _list(client, registered_user["tokens"], limit=2, offset=2).json()
        assert len(rest["items"]) == 1
        assert rest["total"] == 3

        # Ordered by first_name, last_name — Alice, Dana, Eng — so paging is stable.
        seen = [u["email"] for u in page["items"]] + [u["email"] for u in rest["items"]]
        assert seen == ["alice@example.com", "dana@example.com", "eng@example.com"]

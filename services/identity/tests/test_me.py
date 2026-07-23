def test_returns_current_user_with_active_department(client, registered_user):
    token = registered_user["tokens"]["access_token"]
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == registered_user["email"]
    assert body["first_name"] == "Alice"
    assert body["email_verified"] is False
    assert body["is_active"] is True
    assert body["active_role"] == "admin"
    assert body["active_dept_name"] == "Engineering"
    assert body["active_dept_id"]

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

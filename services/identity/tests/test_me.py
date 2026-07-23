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

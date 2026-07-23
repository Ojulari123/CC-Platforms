from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from crescent_core import current_user_dep, require_dept_role
from crescent_core.claims import TokenClaims
from tests.conftest import ISSUER

def _app(jwks_client):
    app = FastAPI()
    current_user = current_user_dep(jwks_client=jwks_client, issuer=ISSUER)
    manager_only = require_dept_role(current_user, "manager", "admin")
    any_member = require_dept_role(current_user)

    @app.get("/me")
    def me(user: TokenClaims = Depends(current_user)):
        return {"user_id": user.user_id, "depts": list(user.dept_ids)}

    @app.get("/departments/{dept_id}/manager-area")
    def manager_area(dept_id: int, user: TokenClaims = Depends(manager_only)):
        return {"user_id": user.user_id, "role": user.role_in(dept_id)}

    @app.get("/departments/{dept_id}/any-member")
    def member_area(dept_id: int, user: TokenClaims = Depends(any_member)):
        return {"ok": True}

    return app

def _bearer(token):
    return {"Authorization": f"Bearer {token}"}

def test_missing_auth_header_returns_401(jwks_client):
    client = TestClient(_app(jwks_client))
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"

def test_valid_token_returns_user(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    r = client.get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 200
    assert r.json() == {"user_id": 42, "depts": [1]}

def test_invalid_token_returns_401(jwks_client):
    client = TestClient(_app(jwks_client))
    r = client.get("/me", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401

def test_role_gate_forbids_wrong_role(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    token = sign_token(memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
    r = client.get("/departments/1/manager-area", headers=_bearer(token))
    assert r.status_code == 403
    assert "manager" in r.json()["detail"]

def test_role_gate_allows_matching_role(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    token = sign_token(memberships=[{"dept_id": 1, "team_id": None, "role": "manager"}])
    r = client.get("/departments/1/manager-area", headers=_bearer(token))
    assert r.status_code == 200
    assert r.json() == {"user_id": 42, "role": "manager"}

def test_role_is_scoped_to_the_department_in_the_url(jwks_client, sign_token):
    """The whole point of the memberships list: manager in 1, engineer in 2."""
    client = TestClient(_app(jwks_client))
    token = sign_token(memberships=[
        {"dept_id": 1, "team_id": None, "role": "manager"},
        {"dept_id": 2, "team_id": None, "role": "engineer"},
    ])
    assert client.get("/departments/1/manager-area", headers=_bearer(token)).status_code == 200
    assert client.get("/departments/2/manager-area", headers=_bearer(token)).status_code == 403

def test_non_member_of_department_is_forbidden(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    token = sign_token(memberships=[{"dept_id": 1, "team_id": None, "role": "admin"}])
    r = client.get("/departments/99/any-member", headers=_bearer(token))
    assert r.status_code == 403
    assert "Not a member" in r.json()["detail"]

def test_platform_admin_passes_every_department_gate(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    token = sign_token(memberships=[], is_platform_admin=True)
    assert client.get("/departments/7/manager-area", headers=_bearer(token)).status_code == 200
    assert client.get("/departments/99/any-member", headers=_bearer(token)).status_code == 200

def test_role_gate_requires_auth(jwks_client):
    # Chained: no token → 401 from current_user, not a bare 403
    client = TestClient(_app(jwks_client))
    r = client.get("/departments/1/manager-area")
    assert r.status_code == 401

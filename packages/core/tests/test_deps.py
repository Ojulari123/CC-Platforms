from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from crescent_core import current_user_dep, require_role
from crescent_core.claims import TokenClaims
from tests.conftest import ISSUER

def _app(jwks_client):
    app = FastAPI()
    current_user = current_user_dep(jwks_client=jwks_client, issuer=ISSUER)
    manager_only = require_role(current_user, "manager", "owner")

    @app.get("/me")
    def me(user: TokenClaims = Depends(current_user)):
        return {"user_id": user.user_id, "role": user.role}

    @app.get("/manager-area")
    def manager_area(user: TokenClaims = Depends(manager_only)):
        return {"user_id": user.user_id, "role": user.role}

    return app

def test_missing_auth_header_returns_401(jwks_client):
    client = TestClient(_app(jwks_client))
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"

def test_valid_token_returns_user(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    r = client.get("/me", headers={"Authorization": f"Bearer {sign_token()}"})
    assert r.status_code == 200
    assert r.json() == {"user_id": 42, "role": "engineer"}

def test_invalid_token_returns_401(jwks_client):
    client = TestClient(_app(jwks_client))
    r = client.get("/me", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401

def test_role_gate_forbids_wrong_role(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    r = client.get("/manager-area", headers={"Authorization": f"Bearer {sign_token(role='engineer')}"})
    assert r.status_code == 403
    assert "manager" in r.json()["detail"]

def test_role_gate_allows_matching_role(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    r = client.get("/manager-area", headers={"Authorization": f"Bearer {sign_token(role='manager')}"})
    assert r.status_code == 200
    assert r.json() == {"user_id": 42, "role": "manager"}

def test_role_gate_requires_auth(jwks_client):
    # Chained: no token → 401 from current_user, not a bare 403
    client = TestClient(_app(jwks_client))
    r = client.get("/manager-area")
    assert r.status_code == 401

import httpx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from crescent_core import JWKSClient, Published, Verdict, current_user_dep, require_dept_role
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
    client = TestClient(_app(jwks_client))
    r = client.get("/departments/1/manager-area")
    assert r.status_code == 401

class _StubChecker:
    def __init__(self, verdict):
        self.verdict = verdict
        self.seen: list[tuple[int, int]] = []

    def check(self, user_id, token_version):
        self.seen.append((user_id, token_version))
        return self.verdict

def _revocation_app(jwks_client, checker):
    app = FastAPI()
    current_user = current_user_dep(jwks_client=jwks_client, issuer=ISSUER, revocation_checker=checker)
    gated = require_dept_role(current_user)

    @app.get("/me")
    def me(user: TokenClaims = Depends(current_user)):
        return {"user_id": user.user_id}

    @app.get("/departments/{dept_id}/any-member")
    def member_area(dept_id: int, user: TokenClaims = Depends(gated)):
        return {"ok": True}

    return app

def test_revocation_checker_gets_the_users_id_and_token_version(jwks_client, sign_token):
    checker = _StubChecker(Verdict.CURRENT)
    client = TestClient(_revocation_app(jwks_client, checker))
    assert client.get("/me", headers=_bearer(sign_token(tv=4))).status_code == 200
    assert checker.seen == [(42, 4)]

def test_stale_token_version_is_rejected(jwks_client, sign_token):
    client = TestClient(_revocation_app(jwks_client, _StubChecker(Verdict.STALE)))
    r = client.get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 401
    assert r.json()["detail"] == "Session is no longer valid"

def test_deleted_user_is_rejected(jwks_client, sign_token):
    r = TestClient(_revocation_app(jwks_client, _StubChecker(Verdict.UNKNOWN))).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 401

def test_identity_outage_does_not_reject(jwks_client, sign_token):
    r = TestClient(_revocation_app(jwks_client, _StubChecker(Verdict.UNAVAILABLE))).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 200

def test_revocation_applies_to_role_gated_routes_too(jwks_client, sign_token):
    client = TestClient(_revocation_app(jwks_client, _StubChecker(Verdict.STALE)))
    assert client.get("/departments/1/any-member", headers=_bearer(sign_token())).status_code == 401

def test_no_checker_keeps_the_previous_behaviour(jwks_client, sign_token):
    client = TestClient(_app(jwks_client))
    assert client.get("/me", headers=_bearer(sign_token(tv=99))).status_code == 200

class _StubPublished:
    def __init__(self, answer):
        self.answer = answer
        self.seen: list[tuple[int, int, str | None]] = []

    def check(self, user_id, token_version, session_id=None):
        self.seen.append((user_id, token_version, session_id))
        return self.answer

def _published_app(jwks_client, published, checker=None):
    app = FastAPI()
    current_user = current_user_dep(jwks_client=jwks_client, issuer=ISSUER, revocation_checker=checker, published_revocations=published)

    @app.get("/me")
    def me(user: TokenClaims = Depends(current_user)):
        return {"user_id": user.user_id}

    return app

def test_published_revocation_rejects_immediately(jwks_client, sign_token):
    published = _StubPublished(Published.REVOKED)
    checker = _StubChecker(Verdict.CURRENT)
    r = TestClient(_published_app(jwks_client, published, checker)).get("/me", headers=_bearer(sign_token(sid="s1")))
    assert r.status_code == 401
    assert r.json()["detail"] == "Session is no longer valid"
    assert published.seen == [(42, 0, "s1")]
    # Rejected on the Redis answer alone; identity was never asked.
    assert checker.seen == []

def test_published_revocation_gets_the_sid_from_the_token(jwks_client, sign_token):
    published = _StubPublished(Published.NOT_REVOKED)
    TestClient(_published_app(jwks_client, published)).get("/me", headers=_bearer(sign_token(sid="fam-digest", tv=7)))
    assert published.seen == [(42, 7, "fam-digest")]

def test_token_without_a_sid_still_gets_checked(jwks_client, sign_token):
    published = _StubPublished(Published.NOT_REVOKED)
    r = TestClient(_published_app(jwks_client, published)).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 200
    assert published.seen == [(42, 0, None)]

def test_no_published_revocation_is_not_a_pass_the_http_check_still_runs(jwks_client, sign_token):
    # The absence of a Redis key proves nothing: identity publishes best-effort, so the
    # token-version lookup has to stay the deciding vote.
    checker = _StubChecker(Verdict.STALE)
    r = TestClient(_published_app(jwks_client, _StubPublished(Published.NOT_REVOKED), checker)).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 401
    assert checker.seen == [(42, 0)]

def test_redis_down_falls_through_to_the_http_check(jwks_client, sign_token):
    checker = _StubChecker(Verdict.STALE)
    r = TestClient(_published_app(jwks_client, _StubPublished(Published.UNAVAILABLE), checker)).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 401
    assert checker.seen == [(42, 0)]

def test_redis_down_and_identity_down_accepts(jwks_client, sign_token):
    # Both fast path and answer of record unavailable: fail open, exactly as before.
    r = TestClient(_published_app(jwks_client, _StubPublished(Published.UNAVAILABLE), _StubChecker(Verdict.UNAVAILABLE))).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 200

def _unreachable_jwks_client():
    def fetcher():
        raise httpx.ConnectError("Connection refused to http://identity.internal:8001/jwks")

    return JWKSClient(jwks_url="http://identity.internal:8001/jwks", fetcher=fetcher, cold_retry_interval_seconds=0.0)

def test_an_unreachable_jwks_is_503_not_500(sign_token):
    # The signing keys can't be reached, so nothing has been judged about the token.
    # 500 said "this server is broken" and, being unhandled, arrived as a traceback.
    r = TestClient(_app(_unreachable_jwks_client()), raise_server_exceptions=False).get("/me", headers=_bearer(sign_token()))
    assert r.status_code == 503
    assert r.json()["detail"] == "Authentication is temporarily unavailable"
    assert r.headers["retry-after"] == "1"

def test_the_503_body_names_nothing_internal(sign_token):
    r = TestClient(_app(_unreachable_jwks_client()), raise_server_exceptions=False).get("/me", headers=_bearer(sign_token()))
    body = r.text
    assert "identity.internal" not in body
    assert "Connection refused" not in body
    assert "ConnectError" not in body

def test_an_unreachable_jwks_still_refuses_the_request(sign_token):
    # Fail closed: unverifiable is never served, only reported differently.
    r = TestClient(_app(_unreachable_jwks_client()), raise_server_exceptions=False).get("/me", headers=_bearer(sign_token()))
    assert r.status_code != 200

def test_a_malformed_token_is_still_401_when_jwks_is_unreachable():
    # Rejected before the keys are ever needed, so an identity outage doesn't blur the
    # difference between "your token is junk" and "we can't check".
    r = TestClient(_app(_unreachable_jwks_client()), raise_server_exceptions=False).get("/me", headers=_bearer("not.a.token"))
    assert r.status_code == 401
    assert r.json()["detail"] == "Malformed token"

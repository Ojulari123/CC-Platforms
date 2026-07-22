from jose import jwt
from app.config import settings

def test_jwks_endpoint_returns_public_key(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    body = r.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"]
    assert key["n"]
    assert key["e"]

def test_access_token_verifies_against_jwks_public_key(client, registered_user):
    access = registered_user["tokens"]["access_token"]
    jwks = client.get("/.well-known/jwks.json").json()
    jwk = jwks["keys"][0]

    payload = jwt.decode(access, jwk, algorithms=["RS256"], issuer=settings.JWT_ISSUER)
    assert payload["email"] == registered_user["email"]
    assert payload["token_type"] == "access"
    assert payload["role"] == "owner"
    assert payload["org_id"] is not None
    assert payload["sub"]

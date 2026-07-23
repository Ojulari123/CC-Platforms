import time
import pytest
from crescent_core import InvalidToken, verify_access_token
from tests.conftest import ISSUER

def test_valid_token_returns_claims(jwks_client, sign_token):
    token = sign_token()
    claims = verify_access_token(token, jwks_client, issuer=ISSUER)
    assert claims.user_id == 42
    assert claims.email == "test@example.com"
    assert claims.dept_id == 1
    assert claims.role == "engineer"
    assert claims.token_version == 0
    assert claims.raw["jti"]

def test_wrong_issuer_rejected(jwks_client, sign_token):
    token = sign_token(iss="malicious-issuer")
    with pytest.raises(InvalidToken):
        verify_access_token(token, jwks_client, issuer=ISSUER)

def test_expired_token_rejected(jwks_client, sign_token):
    token = sign_token(exp=int(time.time()) - 60)
    with pytest.raises(InvalidToken, match="expired"):
        verify_access_token(token, jwks_client, issuer=ISSUER)

def test_refresh_token_type_rejected(jwks_client, sign_token):
    # A token that looks otherwise valid but isn't an access token.
    token = sign_token(token_type="refresh")
    with pytest.raises(InvalidToken, match="Wrong token type"):
        verify_access_token(token, jwks_client, issuer=ISSUER)

def test_malformed_token_rejected(jwks_client):
    with pytest.raises(InvalidToken, match="Malformed"):
        verify_access_token("not.a.jwt", jwks_client, issuer=ISSUER)

def test_missing_kid_rejected(jwks_client, rsa_keypair):
    from jose import jwt as jose_jwt
    import time
    payload = {"sub": "1", "iss": ISSUER, "token_type": "access", "exp": int(time.time()) + 60, "iat": int(time.time())}
    token = jose_jwt.encode(payload, rsa_keypair["private_pem"], algorithm="RS256")  # no kid header
    with pytest.raises(InvalidToken, match="kid"):
        verify_access_token(token, jwks_client, issuer=ISSUER)

def test_unknown_kid_rejected(jwks_client, sign_token, rsa_keypair):
    # Sign with a different key, present a kid the JWKS doesn't have.
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_lib
    from cryptography.hazmat.primitives import serialization
    from jose import jwt as jose_jwt
    other = rsa_lib.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    payload = {"sub": "1", "iss": ISSUER, "token_type": "access", "exp": int(__import__("time").time()) + 60, "iat": int(__import__("time").time())}
    token = jose_jwt.encode(payload, other_pem, algorithm="RS256", headers={"kid": "not-in-jwks"})
    with pytest.raises(InvalidToken, match="Unknown signing key"):
        verify_access_token(token, jwks_client, issuer=ISSUER)

"""Shared fixtures: generate an RSA keypair once per test session, build a JWKS
document from the public key, and offer helpers to sign tokens with the private
key. Nothing hits the network."""
import base64, hashlib, time, uuid
from typing import Any
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt
from crescent_core import JWKSClient

ISSUER = "test-issuer"

def _int_to_b64url(n: int) -> str:
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

@pytest.fixture(scope="session")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    kid = hashlib.sha256(pub_pem.encode()).hexdigest()[:16]
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _int_to_b64url(numbers.n),
        "e": _int_to_b64url(numbers.e),
    }
    return {"private_pem": priv_pem, "public_pem": pub_pem, "kid": kid, "jwk": jwk}

@pytest.fixture
def jwks_doc(rsa_keypair):
    return {"keys": [rsa_keypair["jwk"]]}

@pytest.fixture
def jwks_client(jwks_doc):
    return JWKSClient(jwks_url="http://ignored", fetcher=lambda: jwks_doc)

@pytest.fixture
def sign_token(rsa_keypair):
    """Return a helper that mints an access token with the test keypair. Callers
    override any claim via kwargs; defaults produce a valid token."""

    def _sign(**overrides: Any) -> str:
        now = int(time.time())
        payload = {
            "sub": "42",
            "email": "test@example.com",
            "memberships": [{"dept_id": 1, "team_id": None, "role": "engineer"}],
            "is_platform_admin": False,
            "tv": 0,
            "token_type": "access",
            "iss": ISSUER,
            "iat": now,
            "exp": now + 900,
            "jti": str(uuid.uuid4()),
        }
        payload.update(overrides)
        return jose_jwt.encode(payload, rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]})

    return _sign

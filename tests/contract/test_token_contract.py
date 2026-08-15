"""Identity mints access tokens; Pulse and Forge verify them through
`packages/core`. Nothing else checks that those two agree.

Both suites pass today while disagreeing, because each mints its own fixture
tokens — identity's tests never run core's verifier, and core's tests never run
identity's minter. Rename a claim in one and CI stays green; the break only
appears at runtime in a product. These tests are the seam.
"""
import time
import pytest
from crescent_core import verify_access_token
from crescent_core.verify import InvalidToken

def test_a_real_identity_token_verifies_in_a_product(mint, jwks_client, issuer):
    token = mint(
        user_id=7,
        email="dami@cyphercrescent.com",
        memberships=[{"dept_id": 1, "team_id": 3, "role": "admin"}],
        is_platform_admin=False,
        token_version=0,
    )
    claims = verify_access_token(token, jwks_client, issuer)
    assert claims.user_id == 7
    assert claims.email == "dami@cyphercrescent.com"

def test_every_claim_survives_the_round_trip(mint, jwks_client, issuer):
    """Field-by-field, so a rename or type change fails loudly and specifically."""
    from app.services.auth import session_id_for_family

    session_id = session_id_for_family("fam")
    token = mint(
        user_id=42,
        email="lead@cyphercrescent.com",
        memberships=[
            {"dept_id": 1, "team_id": 3, "role": "manager"},
            {"dept_id": 2, "team_id": None, "role": "engineer"},
        ],
        is_platform_admin=True,
        token_version=5,
        leads=[3, 8],
        session_id=session_id,
    )
    claims = verify_access_token(token, jwks_client, issuer)

    # Revocation reads this and nothing else: if identity renames `sid`, or stops
    # putting it on the token, per-device sign-out goes silently dead in every product.
    assert claims.session_id == session_id
    assert claims.user_id == 42
    assert claims.email == "lead@cyphercrescent.com"
    assert claims.token_version == 5
    assert claims.is_platform_admin is True
    assert claims.dept_ids == (1, 2)
    assert claims.role_in(1) == "manager"
    assert claims.role_in(2) == "engineer"
    assert claims.team_in(1) == 3
    assert claims.team_in(2) is None
    assert claims.leads == (3, 8)
    assert claims.leads_team(3) and not claims.leads_team(99)

def test_leads_defaults_to_empty_when_absent(mint, jwks_client, issuer):
    """Old tokens (and anyone who leads nothing) carry no leads — must parse as
    an empty tuple, never crash."""
    token = mint(user_id=1, email="a@b.com", memberships=[], is_platform_admin=False, token_version=0)
    claims = verify_access_token(token, jwks_client, issuer)
    assert claims.leads == ()
    assert not claims.leads_team(1)

def test_role_does_not_leak_between_departments(mint, jwks_client, issuer):
    """The bug that forced the restructure: one role must not apply everywhere."""
    token = mint(
        user_id=1, email="a@b.com",
        memberships=[
            {"dept_id": 1, "team_id": None, "role": "admin"},
            {"dept_id": 2, "team_id": None, "role": "engineer"},
        ],
        is_platform_admin=False, token_version=0,
    )
    claims = verify_access_token(token, jwks_client, issuer)
    assert claims.role_in(1) == "admin"
    assert claims.role_in(2) == "engineer"
    assert claims.role_in(99) is None
    assert claims.is_member_of(1) and not claims.is_member_of(99)

def test_a_person_with_no_department_verifies_cleanly(mint, jwks_client, issuer):
    """Reachable in production: someone removed from every department still
    holds a valid token until it expires."""
    token = mint(user_id=9, email="nobody@b.com", memberships=[], is_platform_admin=False, token_version=0)
    claims = verify_access_token(token, jwks_client, issuer)
    assert claims.dept_ids == ()
    assert claims.role_in(1) is None

def test_products_reject_a_token_from_a_different_issuer(mint, jwks_client):
    token = mint(user_id=1, email="a@b.com", memberships=[], is_platform_admin=False, token_version=0)
    with pytest.raises(InvalidToken):
        verify_access_token(token, jwks_client, "some-other-issuer")

def test_products_reject_an_expired_token(mint, jwks_client, issuer, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token = mint(user_id=1, email="a@b.com", memberships=[], is_platform_admin=False, token_version=0)
    with pytest.raises(InvalidToken, match="expired"):
        verify_access_token(token, jwks_client, issuer)

def test_products_reject_a_token_signed_by_someone_else(jwks_client, issuer):
    """A token minted with a foreign key must not verify against identity's JWKS."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt

    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    now = int(time.time())
    from app.security import get_key_id
    token = jwt.encode(
        {"sub": "1", "email": "a@b.com", "memberships": [], "is_platform_admin": False,
         "tv": 0, "token_type": "access", "iss": issuer, "iat": now, "exp": now + 900},
        rogue_pem, algorithm="RS256", headers={"kid": get_key_id()},  # claims identity's kid
    )
    with pytest.raises(InvalidToken):
        verify_access_token(token, jwks_client, issuer)

def test_the_published_jwks_is_what_products_consume(jwks_client):
    """Identity's /.well-known/jwks.json shape must match what JWKSClient reads."""
    from app.security import get_key_id, get_public_jwk

    published = get_public_jwk()
    assert {"kty", "use", "alg", "kid", "n", "e"} <= published.keys()
    assert published["kty"] == "RSA"
    assert published["alg"] == "RS256"
    assert jwks_client.get_key(get_key_id()) is not None
    assert jwks_client.get_key("a-kid-that-does-not-exist") is None

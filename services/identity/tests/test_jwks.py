import logging
import os
import tempfile
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
import pytest
from app.config import settings
from app.main import app
from app.security import create_access_token, decode_access_token, get_key_id, reset_key_cache
from app.security.keys import RETIRED_KEY_WARN_THRESHOLD, validate_retired_public_keys

def _write_keypair(directory: str, name: str) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = os.path.join(directory, f"{name}-private.pem")
    pub = os.path.join(directory, f"{name}-public.pem")
    Path(priv).write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    Path(pub).write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    return priv, pub

@pytest.fixture
def rotate():
    original = (settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH, settings.JWT_RETIRED_PUBLIC_KEYS_DIR)

    def _rotate(private_path: str, public_path: str, retired_dir: str) -> None:
        settings.JWT_PRIVATE_KEY_PATH = private_path
        settings.JWT_PUBLIC_KEY_PATH = public_path
        settings.JWT_RETIRED_PUBLIC_KEYS_DIR = retired_dir
        reset_key_cache()

    yield _rotate
    settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH, settings.JWT_RETIRED_PUBLIC_KEYS_DIR = original
    reset_key_cache()

def _mint() -> str:
    return create_access_token(user_id=1, email="rot@example.com", memberships=[], is_platform_admin=False, token_version=0)

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
    assert payload["is_platform_admin"] is True
    assert len(payload["memberships"]) == 1
    assert payload["memberships"][0]["role"] == "admin"
    assert payload["memberships"][0]["dept_id"] is not None
    assert payload["sub"]

def test_single_keypair_with_no_retired_dir_publishes_one_key(client, rotate):
    with tempfile.TemporaryDirectory() as d:
        priv, pub = _write_keypair(d, "solo")
        rotate(priv, pub, os.path.join(d, "retired-does-not-exist"))
        body = client.get("/.well-known/jwks.json").json()
        assert len(body["keys"]) == 1
        assert body["keys"][0]["kid"] == get_key_id()
        assert decode_access_token(_mint())["email"] == "rot@example.com"

def test_distinct_keys_get_distinct_kids(rotate):
    with tempfile.TemporaryDirectory() as d:
        a_priv, a_pub = _write_keypair(d, "a")
        b_priv, b_pub = _write_keypair(d, "b")
        retired = os.path.join(d, "retired")
        rotate(a_priv, a_pub, retired)
        kid_a = get_key_id()
        rotate(b_priv, b_pub, retired)
        assert get_key_id() != kid_a

class TestGracefulHandover:
    def test_old_token_still_verifies_and_new_tokens_use_the_new_key(self, client, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")

            rotate(a_priv, a_pub, retired)
            kid_a = get_key_id()
            token_a = _mint()

            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            kid_b = get_key_id()
            token_b = _mint()

            assert kid_b != kid_a
            assert jwt.get_unverified_header(token_a)["kid"] == kid_a
            assert jwt.get_unverified_header(token_b)["kid"] == kid_b
            assert decode_access_token(token_a)["email"] == "rot@example.com"
            assert decode_access_token(token_b)["email"] == "rot@example.com"

            published = {k["kid"]: k for k in client.get("/.well-known/jwks.json").json()["keys"]}
            assert set(published) == {kid_a, kid_b}
            for token, kid in ((token_a, kid_a), (token_b, kid_b)):
                assert jwt.decode(token, published[kid], algorithms=["RS256"], issuer=settings.JWT_ISSUER)["sub"] == "1"

    def test_active_key_is_published_first(self, client, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            _, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")
            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            assert client.get("/.well-known/jwks.json").json()["keys"][0]["kid"] == get_key_id()

    def test_retiring_the_old_key_out_stops_it_verifying(self, client, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")

            rotate(a_priv, a_pub, retired)
            kid_a = get_key_id()
            token_a = _mint()

            archived = Path(os.path.join(retired, "public-a.pem"))
            archived.write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            assert decode_access_token(token_a)["sub"] == "1"

            archived.unlink()
            reset_key_cache()
            assert [k["kid"] for k in client.get("/.well-known/jwks.json").json()["keys"]] == [get_key_id()]
            assert kid_a not in [k["kid"] for k in client.get("/.well-known/jwks.json").json()["keys"]]
            with pytest.raises(HTTPException) as exc:
                decode_access_token(token_a)
            assert exc.value.status_code == 401

    def test_the_same_public_key_in_both_places_is_published_once(self, client, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(a_priv, a_pub, retired)
            assert len(client.get("/.well-known/jwks.json").json()["keys"]) == 1

    def test_retired_key_cannot_sign(self, client, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            _, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")
            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            for _ in range(3):
                assert jwt.get_unverified_header(_mint())["kid"] == get_key_id()

def test_token_with_an_unknown_kid_is_rejected(rotate):
    with tempfile.TemporaryDirectory() as d:
        a_priv, a_pub = _write_keypair(d, "a")
        rogue_priv, _ = _write_keypair(d, "rogue")
        rotate(a_priv, a_pub, os.path.join(d, "retired"))
        forged = jwt.encode(
            {"sub": "1", "token_type": "access", "iss": settings.JWT_ISSUER},
            Path(rogue_priv).read_text(), algorithm="RS256", headers={"kid": "not-a-real-kid"},
        )
        with pytest.raises(HTTPException) as exc:
            decode_access_token(forged)
        assert exc.value.status_code == 401

def test_malformed_token_is_rejected():
    with pytest.raises(HTTPException) as exc:
        decode_access_token("not-a-jwt")
    assert exc.value.status_code == 401

def test_non_rsa_key_in_the_retired_dir_is_refused(client, rotate):
    with tempfile.TemporaryDirectory() as d:
        retired = os.path.join(d, "retired")
        os.makedirs(retired)
        a_priv, a_pub = _write_keypair(d, "a")
        ec_key = ec.generate_private_key(ec.SECP256R1())
        Path(os.path.join(retired, "public-ec.pem")).write_bytes(ec_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        rotate(a_priv, a_pub, retired)
        with pytest.raises(RuntimeError, match="Only RSA"):
            client.get("/.well-known/jwks.json")

def test_missing_key_file_names_the_path(rotate):
    with tempfile.TemporaryDirectory() as d:
        rotate(os.path.join(d, "gone.pem"), os.path.join(d, "gone.pub.pem"), os.path.join(d, "retired"))
        with pytest.raises(FileNotFoundError, match="JWT key not found"):
            _mint()

class TestStartupKeyValidation:
    def test_bad_retired_key_refuses_the_boot_and_names_the_file(self, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            ec_key = ec.generate_private_key(ec.SECP256R1())
            bad = Path(os.path.join(retired, "public-ec.pem"))
            bad.write_bytes(ec_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            rotate(a_priv, a_pub, retired)
            with pytest.raises(RuntimeError, match=str(bad)):
                with TestClient(app):
                    pass

    def test_garbage_file_refuses_the_boot(self, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            Path(os.path.join(retired, "notes.pem")).write_text("this is not a key at all")
            rotate(a_priv, a_pub, retired)
            with pytest.raises(RuntimeError, match="not a usable RSA public key"):
                with TestClient(app):
                    pass

    def test_a_private_key_left_in_the_retired_dir_refuses_the_boot(self, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            a_priv, a_pub = _write_keypair(d, "a")
            Path(os.path.join(retired, "private-oops.pem")).write_text(Path(a_priv).read_text())
            rotate(a_priv, a_pub, retired)
            with pytest.raises(RuntimeError, match="private-oops.pem"):
                with TestClient(app):
                    pass

    def test_missing_retired_dir_boots_normally(self, rotate):
        with tempfile.TemporaryDirectory() as d:
            a_priv, a_pub = _write_keypair(d, "a")
            rotate(a_priv, a_pub, os.path.join(d, "no-such-dir"))
            assert validate_retired_public_keys() == ()
            with TestClient(app) as c:
                assert len(c.get("/.well-known/jwks.json").json()["keys"]) == 1

    def test_valid_retired_keys_boot_normally_and_are_published(self, rotate):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            _, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")
            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            assert len(validate_retired_public_keys()) == 1
            with TestClient(app) as c:
                assert len(c.get("/.well-known/jwks.json").json()["keys"]) == 2

    def test_a_file_that_goes_bad_after_boot_cannot_take_jwks_down(self, rotate):
        """Startup reads the directory once and the process serves that set for its
        life, so a stray file dropped in later is invisible until the next restart,
        which is where it gets caught."""
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            _, a_pub = _write_keypair(d, "a")
            b_priv, b_pub = _write_keypair(d, "b")
            Path(os.path.join(retired, "public-a.pem")).write_text(Path(a_pub).read_text())
            rotate(b_priv, b_pub, retired)
            with TestClient(app) as c:
                # Dropped in AFTER startup validated and cached the directory. If the
                # keys were re-read per request this would 500 the endpoint.
                Path(os.path.join(retired, "junk.pem")).write_text("not a key")
                assert len(c.get("/.well-known/jwks.json").json()["keys"]) == 2

    def test_a_pile_of_retired_keys_warns_at_startup(self, rotate, caplog):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            b_priv, b_pub = _write_keypair(d, "active")
            for i in range(RETIRED_KEY_WARN_THRESHOLD):
                _, pub = _write_keypair(d, f"old{i}")
                Path(os.path.join(retired, f"public-{i}.pem")).write_text(Path(pub).read_text())
            rotate(b_priv, b_pub, retired)
            with caplog.at_level(logging.WARNING, logger="app.main"):
                with TestClient(app):
                    pass
            assert any("5 retired signing keys" in r.getMessage() for r in caplog.records)

    def test_a_normal_number_of_retired_keys_stays_quiet(self, rotate, caplog):
        with tempfile.TemporaryDirectory() as d:
            retired = os.path.join(d, "retired")
            os.makedirs(retired)
            b_priv, b_pub = _write_keypair(d, "active")
            _, pub = _write_keypair(d, "old")
            Path(os.path.join(retired, "public-0.pem")).write_text(Path(pub).read_text())
            rotate(b_priv, b_pub, retired)
            with caplog.at_level(logging.WARNING, logger="app.main"):
                with TestClient(app):
                    pass
            assert not [r for r in caplog.records if "retired signing keys" in r.getMessage()]

"""Cross-service contract tests.

These live at the repo root, outside both packages, because they need to import
identity AND crescent_core at once — and the dependency rule says core must
never import from services/*. A test that depends on both breaks no rule; a
package that does would.

Everything here is in-memory: an ephemeral RSA keypair and SQLite, no network,
no database server.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "services" / "identity"))
sys.path.insert(0, str(_ROOT / "packages" / "core"))

_keys = tempfile.mkdtemp(prefix="contract_keys_")
_priv = os.path.join(_keys, "private.pem")
_pub = os.path.join(_keys, "public.pem")
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
Path(_priv).write_bytes(_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
))
Path(_pub).write_bytes(_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_PRIVATE_KEY_PATH"] = _priv
os.environ["JWT_PUBLIC_KEY_PATH"] = _pub
os.environ["BREVO_API_KEY"] = ""
os.environ["EMAIL_FROM"] = ""


@pytest.fixture(scope="session")
def issuer():
    from app.config import settings
    return settings.JWT_ISSUER


@pytest.fixture(scope="session")
def mint():
    """Mint a token exactly the way identity mints one in production."""
    from app.security import create_access_token
    return create_access_token


@pytest.fixture(scope="session")
def jwks_client():
    """A products-side JWKS client fed by identity's own published document —
    no hand-written fixture in between, which is the whole point."""
    from app.security import get_public_jwk
    from crescent_core import JWKSClient
    return JWKSClient("http://identity-not-called", fetcher=lambda: {"keys": [get_public_jwk()]})

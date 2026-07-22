import base64, hashlib
from functools import lru_cache
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from app.config import settings

def _read(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JWT key not found at {p}. Generate a keypair — see services/identity/README.md.")
    return p.read_text()

@lru_cache(maxsize=1)
def get_private_key_pem() -> str:
    return _read(settings.JWT_PRIVATE_KEY_PATH)

@lru_cache(maxsize=1)
def get_public_key_pem() -> str:
    return _read(settings.JWT_PUBLIC_KEY_PATH)

@lru_cache(maxsize=1)
def get_key_id() -> str:
    """Stable kid derived from the public key so it survives restarts.
    Same input = same kid; only changes when the key rotates."""
    return hashlib.sha256(get_public_key_pem().encode()).hexdigest()[:16]

def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

@lru_cache(maxsize=1)
def get_public_jwk() -> dict:
    """The public key as a JWK — what identity publishes at /.well-known/jwks.json."""
    public_key = serialization.load_pem_public_key(get_public_key_pem().encode())
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise RuntimeError("Only RSA public keys are supported")
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": settings.JWT_ALGORITHM,
        "kid": get_key_id(),
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }

def reset_key_cache() -> None:
    """Clear cached keys — used by tests when swapping keypairs between runs."""
    get_private_key_pem.cache_clear()
    get_public_key_pem.cache_clear()
    get_key_id.cache_clear()
    get_public_jwk.cache_clear()

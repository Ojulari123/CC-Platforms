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

def _key_id_for(public_pem: str) -> str:
    return hashlib.sha256(public_pem.encode()).hexdigest()[:16]

@lru_cache(maxsize=1)
def get_key_id() -> str:
    """Stable kid derived from the public key so it survives restarts.
    Same input = same kid; only changes when the key rotates."""
    return _key_id_for(get_public_key_pem())

@lru_cache(maxsize=1)
def get_retired_public_key_pems() -> tuple[str, ...]:
    """Public halves of previous signing keys. Retiring one is dropping its .pem in
    JWT_RETIRED_PUBLIC_KEYS_DIR; a missing directory means none."""
    directory = Path(settings.JWT_RETIRED_PUBLIC_KEYS_DIR)
    if not directory.is_dir():
        return ()
    return tuple(p.read_text() for p in sorted(directory.glob("*.pem")))

# Above this, someone is skipping the last phase of a rotation. Keep in step with
# the same threshold in scripts/rotate-identity-keys.sh.
RETIRED_KEY_WARN_THRESHOLD = 5

def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

def _jwk_from_pem(public_pem: str) -> dict:
    public_key = serialization.load_pem_public_key(public_pem.encode())
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise RuntimeError("Only RSA public keys are supported")
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": settings.JWT_ALGORITHM,
        "kid": _key_id_for(public_pem),
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }

@lru_cache(maxsize=1)
def get_public_jwk() -> dict:
    """The ACTIVE public key as a JWK — the only key identity signs with."""
    return _jwk_from_pem(get_public_key_pem())

@lru_cache(maxsize=1)
def get_public_jwks() -> tuple[dict, ...]:
    """Everything published at /.well-known/jwks.json: active key first, then retired
    ones. Retired keys verify but never sign — that is what makes a rotation a
    handover rather than a cutover."""
    jwks = [get_public_jwk()]
    seen = {jwks[0]["kid"]}
    for pem in get_retired_public_key_pems():
        jwk = _jwk_from_pem(pem)
        if jwk["kid"] not in seen:
            seen.add(jwk["kid"])
            jwks.append(jwk)
    return tuple(jwks)

@lru_cache(maxsize=1)
def _verification_keys_by_kid() -> dict[str, str]:
    keys = {get_key_id(): get_public_key_pem()}
    for pem in get_retired_public_key_pems():
        keys.setdefault(_key_id_for(pem), pem)
    return keys

def get_verification_key_pem(kid: str | None) -> str:
    """PEM to verify a token with, picked by its `kid` header so identity accepts
    its own pre-rotation tokens. An unknown or absent kid falls back to the active
    key: the signature check, not this lookup, is what rejects a forged token."""
    if kid:
        pem = _verification_keys_by_kid().get(kid)
        if pem is not None:
            return pem
    return get_public_key_pem()

def validate_retired_public_keys() -> tuple[str, ...]:
    """Raise on the first unusable retired .pem, naming it — at startup, so a bad file
    refuses the boot rather than 500ing /.well-known/jwks.json later. Also warms the
    cache. Returns their kids. See README "Signing keys and rotation"."""
    directory = Path(settings.JWT_RETIRED_PUBLIC_KEYS_DIR)
    if not directory.is_dir():
        return ()
    kids = []
    for path in sorted(directory.glob("*.pem")):
        try:
            kids.append(_jwk_from_pem(path.read_text())["kid"])
        except Exception as e:
            raise RuntimeError(
                f"Retired public key {path} is not a usable RSA public key ({e}). "
                "Identity will not start: this file is published at /.well-known/jwks.json, "
                "which every service uses to verify tokens. Remove it, or replace it with "
                "the PEM public key it was meant to be."
            ) from e
    get_retired_public_key_pems()
    return tuple(kids)

def reset_key_cache() -> None:
    """Clear cached keys — used by tests when swapping keypairs between runs."""
    get_private_key_pem.cache_clear()
    get_public_key_pem.cache_clear()
    get_key_id.cache_clear()
    get_retired_public_key_pems.cache_clear()
    get_public_jwk.cache_clear()
    get_public_jwks.cache_clear()
    _verification_keys_by_kid.cache_clear()

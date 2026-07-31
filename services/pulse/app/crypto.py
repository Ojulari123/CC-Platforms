"""Symmetric encryption for secrets at rest, and for the OAuth `state`.

Fernet = authenticated symmetric encryption from the `cryptography` library (it
comes in via crescent_core). The key lives ONLY in the environment
(GITHUB_TOKEN_ENC_KEY), never in the database — so a leaked database doesn't hand
over anyone's GitHub token.

Two uses:
- encrypt/decrypt: the stored GitHub access token.
- sign_state/read_state: the OAuth `state` blob. The callback arrives as a plain
  browser redirect (no auth header), so which identity user is connecting has to
  travel in state — signed + expiring so it can't be forged or replayed.
"""
import json
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

class TokenEncryptionNotConfigured(RuntimeError):
    """GITHUB_TOKEN_ENC_KEY is missing."""

class InvalidStateError(Exception):
    """The OAuth state blob was forged, tampered with, or expired."""

def _fernet() -> Fernet:
    if not settings.GITHUB_TOKEN_ENC_KEY:
        raise TokenEncryptionNotConfigured(
            "Set GITHUB_TOKEN_ENC_KEY (a Fernet key) before connecting GitHub accounts"
        )
    return Fernet(settings.GITHUB_TOKEN_ENC_KEY.encode())

def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()

def sign_state(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()

def read_state(token: str, max_age_seconds: int) -> dict:
    try:
        raw = _fernet().decrypt(token.encode(), ttl=max_age_seconds)
    except InvalidToken as exc:
        raise InvalidStateError("Invalid or expired state") from exc
    return json.loads(raw)

"""The Fernet key lives ONLY in the environment (GITHUB_TOKEN_ENC_KEY), never in the
database, so a leaked database doesn't hand over anyone's GitHub token.
"""
import json
import logging
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

logger = logging.getLogger(__name__)

class TokenEncryptionNotConfigured(RuntimeError):
    """A missing key is a server configuration problem, not a bad request: callers turn
    this into a 503. Which variable is missing stays in the log, never in the message."""

class InvalidStateError(Exception):
    pass

def _fernet() -> Fernet:
    if not settings.GITHUB_TOKEN_ENC_KEY:
        logger.error("GitHub token encryption is not configured: GITHUB_TOKEN_ENC_KEY (a Fernet key) must be set")
        raise TokenEncryptionNotConfigured("GitHub token encryption is not configured on this server")
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

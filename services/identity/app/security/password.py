import re
import bcrypt
from fastapi import HTTPException

# bcrypt only reads the first 72 BYTES of a password and ignores the rest —
# silently. Before this cap, a 103-character password could be logged into with
# just its first 72 characters, while the API advertised a 128-character limit.
# Rejecting is honest; accepting-and-truncating gives false confidence.
# Bytes, not characters: one emoji or accented letter can be 2–4 bytes.
MAX_PASSWORD_BYTES = 72

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def validate_password(password: str) -> str:
    encoded_length = len(password.encode("utf-8"))
    if encoded_length > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Password is too long ({encoded_length} bytes; the limit is {MAX_PASSWORD_BYTES}). "
                "Accented characters and emoji count as more than one byte each."
            ),
        )

    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("one lowercase letter")
    if not re.search(r"[0-9]", password):
        errors.append("one number")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("one special character")
    if errors:
        raise HTTPException(status_code=400, detail=f"Password must contain: {', '.join(errors)}")
    return password

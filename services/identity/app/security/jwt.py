import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from app.config import settings
from app.security.keys import get_key_id, get_private_key_pem, get_public_key_pem

class TokenPayload(dict):
    """Thin dict wrapper so callers can do payload.user_id etc."""

    @property
    def user_id(self) -> int:
        return int(self["sub"])

    @property
    def memberships(self) -> list[dict]:
        return self.get("memberships", [])

    @property
    def is_platform_admin(self) -> bool:
        return bool(self.get("is_platform_admin", False))

    def role_in(self, dept_id: int) -> str | None:
        """The caller's role in one department, or None if they're not in it."""
        for m in self.memberships:
            if m.get("dept_id") == dept_id:
                return m.get("role")
        return None

    @property
    def token_version(self) -> int:
        return int(self.get("tv", 0))

def create_access_token(*, user_id: int, email: str, memberships: list[dict], is_platform_admin: bool, token_version: int) -> str:
    """Carries EVERY department membership, not one 'active' one. A person can be
    an admin in Engineering and an engineer in Data at the same time; a single
    dept_id claim would have to pick one arbitrarily and silently lock them out
    of the other."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "memberships": memberships,
        "is_platform_admin": is_platform_admin,
        "tv": token_version,
        "token_type": "access",
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    headers = {"kid": get_key_id()}
    return jwt.encode(payload, get_private_key_pem(), algorithm=settings.JWT_ALGORITHM, headers=headers)

def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, get_public_key_pem(), algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    if payload.get("token_type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return TokenPayload(payload)

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

    @property
    def leads(self) -> list[int]:
        return self.get("leads", [])

def create_access_token(*, user_id: int, email: str, memberships: list[dict], is_platform_admin: bool, token_version: int, leads: list[int] | None = None) -> str:
    """Carries EVERY department membership, not one 'active' one. A person can be
    an admin in Engineering and an engineer in Data at the same time; a single
    dept_id claim would have to pick one arbitrarily and silently lock them out
    of the other.

    `leads` is the team ids this person is the named lead of (Team.manager_user_id).
    Pulse needs it to route report approvals — "may this caller approve a report
    for team 3?" — without calling identity's DB on every request. Approval is a
    Pulse decision made purely from the token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "memberships": memberships,
        "is_platform_admin": is_platform_admin,
        "leads": leads or [],
        "tv": token_version,
        "token_type": "access",
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    headers = {"kid": get_key_id()}
    return jwt.encode(payload, get_private_key_pem(), algorithm=settings.JWT_ALGORITHM, headers=headers)

def create_service_token(*, client_id: str, scopes: str) -> str:
    """Mint a token for a service authenticating as ITSELF (not a user).
    Deliberately kept separate from create_access_token: `sub` is `svc:<client>`
    not a user id, `token_type` is "service" (so it can never pass a user-token
    check), and it carries a `scope` string instead of memberships/roles. Short
    life (SERVICE_TOKEN_EXPIRE_MINUTES) because it's cheap to re-mint."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"svc:{client_id}",
        "token_type": "service",
        "scope": scopes,
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.SERVICE_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    headers = {"kid": get_key_id()}
    return jwt.encode(payload, get_private_key_pem(), algorithm=settings.JWT_ALGORITHM, headers=headers)

def decode_service_token(token: str) -> dict:
    """Verify a service token with the LOCAL public key. Mirrors decode_access_token's
    checks (signature, expiry, issuer) but REQUIRES token_type "service" — a user
    access token presented here is rejected. Does NOT int-cast `sub` (it's svc:<id>)."""
    try:
        payload = jwt.decode(token, get_public_key_pem(), algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    if payload.get("token_type") != "service":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return payload

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

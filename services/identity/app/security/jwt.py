import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from app.config import settings
from app.security.keys import get_key_id, get_private_key_pem, get_verification_key_pem

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
    """Carries EVERY membership, not one 'active' one — a single dept_id claim would
    have to pick one and lock the person out of the other. `leads` is the teams they
    lead, so Pulse can route approvals from the token without calling identity."""
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

def _verification_key_for(token: str) -> str:
    """Reading the header before the signature is checked is safe here: the kid only
    selects which published key to try, and a token naming a key it wasn't signed
    with still fails verification."""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError:
        kid = None
    return get_verification_key_pem(kid)

def create_service_token(*, client_id: str, scopes: str) -> str:
    """A service authenticating as ITSELF. Kept separate from create_access_token so
    it can never pass a user-token check: `sub` is svc:<client>, token_type is
    "service", and it carries a scope string instead of memberships."""
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
        payload = jwt.decode(token, _verification_key_for(token), algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    if payload.get("token_type") != "service":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return payload

def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, _verification_key_for(token), algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
    if payload.get("token_type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return TokenPayload(payload)

from jose import ExpiredSignatureError, JWTError, jwt
from crescent_core.claims import TokenClaims
from crescent_core.jwks import JWKSClient

class InvalidToken(Exception):
    """Raised when an access token fails any part of verification.
    Message is safe to surface to clients (no key material, no user data)."""

class _MissingKid(InvalidToken):
    pass

def verify_access_token(token: str, jwks_client: JWKSClient, issuer: str, algorithms: tuple[str, ...] = ("RS256",)) -> TokenClaims:
    """Verify signature, expiry, issuer, and token_type. Returns TokenClaims on
    success, raises InvalidToken on any failure. Never touches identity's DB."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise InvalidToken("Malformed token")

    kid = header.get("kid")
    if not kid:
        raise _MissingKid("Token missing kid header")

    key = jwks_client.get_key(kid)
    if key is None:
        raise InvalidToken("Unknown signing key")

    try:
        payload = jwt.decode(token, key, algorithms=list(algorithms), issuer=issuer)
    except ExpiredSignatureError:
        raise InvalidToken("Token has expired")
    except JWTError as e:
        raise InvalidToken(f"Invalid token: {e}")

    if payload.get("token_type") != "access":
        raise InvalidToken("Wrong token type")

    return TokenClaims.from_payload(payload)

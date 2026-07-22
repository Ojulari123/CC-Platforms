from fastapi import APIRouter
from app.security import get_public_jwk

router = APIRouter(tags=["jwks"])

@router.get("/.well-known/jwks.json")
def jwks() -> dict:
    """Public key(s) products use to verify access tokens. The private signing key
    never leaves identity — this endpoint is the only piece of the JWT trust chain
    that any other service ever sees."""
    return {"keys": [get_public_jwk()]}

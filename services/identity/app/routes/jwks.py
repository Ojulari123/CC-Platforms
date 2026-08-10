from fastapi import APIRouter
from app.security import get_public_jwks

router = APIRouter(tags=["jwks"])

@router.get("/.well-known/jwks.json")
def jwks() -> dict:
    return {"keys": list(get_public_jwks())}

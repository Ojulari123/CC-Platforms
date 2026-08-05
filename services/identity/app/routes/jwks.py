from fastapi import APIRouter
from app.security import get_public_jwk

router = APIRouter(tags=["jwks"])

@router.get("/.well-known/jwks.json")
def jwks() -> dict:
    return {"keys": [get_public_jwk()]}

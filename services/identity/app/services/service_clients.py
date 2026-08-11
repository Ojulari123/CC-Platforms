from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import ServiceClient
from app.security import create_service_token, hash_password, verify_password

# Burned on an unknown client_id so a bad id and a bad secret take the same time.
_DUMMY_SECRET_HASH = hash_password("service-client-does-not-exist")

# Explicit so seeding can't silently over-grant. Split by sensitivity: a service that
# only draws names never gets the email one, and tokens:verify carries no PII at all.
PULSE_SCOPES = "users:read:email users:read:profile tokens:verify"
# Forge renders no names or addresses; it only needs to spot a killed session.
FORGE_SCOPES = "tokens:verify"

def seed_service_client(db: Session, *, client_id: str, secret: str, scopes: str) -> ServiceClient:
    """Rotates the hashed secret and scopes but never touches is_active, because a
    re-seed on every boot would otherwise undo a manual revocation."""
    client = db.scalar(select(ServiceClient).where(ServiceClient.client_id == client_id))
    if client is None:
        client = ServiceClient(client_id=client_id, is_active=True)
        db.add(client)
    client.client_secret_hash = hash_password(secret)
    client.scopes = scopes
    db.commit()
    db.refresh(client)
    return client

def issue_client_credentials_token(db: Session, *, client_id: str, client_secret: str) -> tuple[str, int]:
    client = db.scalar(select(ServiceClient).where(ServiceClient.client_id == client_id))
    if client is None:
        verify_password(client_secret, _DUMMY_SECRET_HASH)  # burn equal time, no enumeration
        raise HTTPException(status_code=401, detail="Invalid client credentials")
    if not verify_password(client_secret, client.client_secret_hash):
        raise HTTPException(status_code=401, detail="Invalid client credentials")
    if not client.is_active:
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    token = create_service_token(client_id=client.client_id, scopes=client.scopes)
    return token, settings.SERVICE_TOKEN_EXPIRE_MINUTES * 60

def _seed_if_configured(db: Session, *, client_id: str, secret: str, scopes: str) -> ServiceClient | None:
    if not secret:
        return None
    return seed_service_client(db, client_id=client_id, secret=secret, scopes=scopes)

def seed_pulse_client(db: Session) -> ServiceClient | None:
    return _seed_if_configured(
        db,
        client_id=settings.PULSE_CLIENT_ID,
        secret=settings.PULSE_CLIENT_SECRET,
        scopes=PULSE_SCOPES,
    )

def seed_forge_client(db: Session) -> ServiceClient | None:
    return _seed_if_configured(
        db,
        client_id=settings.FORGE_CLIENT_ID,
        secret=settings.FORGE_CLIENT_SECRET,
        scopes=FORGE_SCOPES,
    )

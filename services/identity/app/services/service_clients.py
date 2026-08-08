from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import ServiceClient
from app.security import create_service_token, hash_password, verify_password

# Burned when the client_id is unknown so a bad id and a bad secret take the same
# time — no way to probe which client_ids exist by timing.
_DUMMY_SECRET_HASH = hash_password("service-client-does-not-exist")

# Scopes the Pulse client is allowed to request. Kept explicit so seeding can't
# silently over-grant — a new capability is a deliberate edit here.
PULSE_SCOPES = "users:read:email"

def seed_service_client(db: Session, *, client_id: str, secret: str, scopes: str) -> ServiceClient:
    """Idempotent upsert of one service client. Safe to call on every boot: on an
    existing row it rotates the stored (hashed) secret and scopes but NEVER touches
    is_active — a client revoked via is_active=False stays revoked across restarts,
    otherwise this seed would silently undo revocation. is_active is only set True
    when the row is first CREATED. Only the bcrypt hash is stored, never the raw secret."""
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
    """Verify a service client's credentials and mint a scoped service token.
    Returns (token, expires_in_seconds). Raises 401 on any failure — unknown
    client, wrong secret, or deactivated — with the SAME message, so a caller
    can't tell which part failed."""
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

def seed_pulse_client(db: Session) -> ServiceClient | None:
    """Startup seed for Pulse. No-op unless PULSE_CLIENT_SECRET is configured, so
    an unconfigured environment (import check, fresh boot) never crashes."""
    if not settings.PULSE_CLIENT_SECRET:
        return None
    return seed_service_client(
        db,
        client_id=settings.PULSE_CLIENT_ID,
        secret=settings.PULSE_CLIENT_SECRET,
        scopes=PULSE_SCOPES,
    )

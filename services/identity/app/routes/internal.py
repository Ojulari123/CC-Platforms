from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.oauth import EmailLookupRequest, EmailLookupResponse, UserEmail
from app.security import require_service_scope

router = APIRouter(prefix="/internal", tags=["internal"])

_emails_reader = require_service_scope("users:read:email")

@router.post("/users/emails", response_model=EmailLookupResponse)
def lookup_emails(payload: EmailLookupRequest, _=Depends(_emails_reader), db: Session = Depends(get_db)) -> EmailLookupResponse:
    """Resolve user_id -> email for another service (e.g. Pulse turning synced
    GitHub authors into people). Service-token + scope gated. Unknown ids are
    silently omitted rather than erroring, so a partial id list still succeeds."""
    if not payload.user_ids:
        return EmailLookupResponse(users=[])
    rows = db.execute(select(User.id, User.email).where(User.id.in_(payload.user_ids))).all()
    return EmailLookupResponse(users=[UserEmail(user_id=uid, email=email) for uid, email in rows])

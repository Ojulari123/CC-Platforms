from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from app.db import get_db
from app.rate_limit import limiter
from app.schemas.auth import TokenPair
from app.schemas.departments import InviteAccept, InvitePreview
from app.services import invites as invites_service

router = APIRouter(prefix="/invites", tags=["invites"])

@router.get("/preview", response_model=InvitePreview)
@limiter.limit("20/minute")
def preview_invite(request: Request, token: str = Query(...), db: Session = Depends(get_db)) -> InvitePreview:
    return invites_service.preview_invite(db, token)

@router.post("/accept", response_model=TokenPair)
@limiter.limit("5/minute")
def accept_invite(request: Request, payload: InviteAccept, db: Session = Depends(get_db)) -> TokenPair:
    return invites_service.accept_invite(db, payload)

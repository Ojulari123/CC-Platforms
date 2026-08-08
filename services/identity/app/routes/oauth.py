from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.db import get_db
from app.rate_limit import limiter
from app.schemas.oauth import ClientCredentialsRequest, ServiceTokenResponse
from app.services import service_clients as service_client_service

router = APIRouter(prefix="/oauth", tags=["oauth"])

@router.post("/token", response_model=ServiceTokenResponse)
@limiter.limit("10/minute")
def token(request: Request, payload: ClientCredentialsRequest, db: Session = Depends(get_db)) -> ServiceTokenResponse:
    """OAuth2 client-credentials grant: a service authenticates as itself and gets
    a short-lived, scoped service token. Only client_credentials is supported —
    there's no user, password, or refresh flow here."""
    if payload.grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="Unsupported grant_type; expected 'client_credentials'")

    access_token, expires_in = service_client_service.issue_client_credentials_token(
        db, client_id=payload.client_id, client_secret=payload.client_secret
    )
    return ServiceTokenResponse(access_token=access_token, expires_in=expires_in)

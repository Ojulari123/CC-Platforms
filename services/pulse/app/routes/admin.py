from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.auth import current_user
from app.db import get_db
from app.schemas.admin import LlmUsageSummary
from app.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/llm-usage", response_model=LlmUsageSummary)
def llm_usage(since: date | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> LlmUsageSummary:
    """Total LLM tokens consumed and how many generations ran. Platform admin only."""
    return admin_service.llm_usage_summary(db, user, since=since)

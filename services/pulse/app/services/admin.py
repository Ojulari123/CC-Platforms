"""Platform-admin view of token usage. 

It shows when the token usage rolls up so the admin can see total
consumption and know when to top up the LLM account (no one else see this.)"""
from datetime import date, datetime, time, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import LlmUsage
from app.schemas.admin import LlmUsageSummary

def llm_usage_summary(db: Session, user: TokenClaims, since: date | None = None) -> LlmUsageSummary:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin only")
    q = select(func.coalesce(func.sum(LlmUsage.tokens), 0), func.count()).select_from(LlmUsage)
    if since is not None:
        lo = datetime.combine(since, time.min, tzinfo=timezone.utc)
        q = q.where(LlmUsage.created_at >= lo)
    total_tokens, generation_count = db.execute(q).one()
    return LlmUsageSummary(total_tokens=total_tokens, generation_count=generation_count)

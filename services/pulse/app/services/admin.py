from datetime import date, datetime, time, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import LlmUsage
from app.schemas.admin import LlmUsageByKind, LlmUsageSummary

def llm_usage_summary(db: Session, user: TokenClaims, since: date | None = None) -> LlmUsageSummary:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin only")
    q = select(func.coalesce(func.sum(LlmUsage.tokens), 0), func.count()).select_from(LlmUsage)
    if since is not None:
        lo = datetime.combine(since, time.min, tzinfo=timezone.utc)
        q = q.where(LlmUsage.created_at >= lo)
    total_tokens, generation_count = db.execute(q).one()

    # Reports are no longer the only thing that spends tokens, so the totals alone
    # can't say which surface the bill came from.
    kq = select(LlmUsage.kind, func.coalesce(func.sum(LlmUsage.tokens), 0), func.count()).group_by(LlmUsage.kind)
    if since is not None:
        kq = kq.where(LlmUsage.created_at >= lo)
    by_kind = [
        LlmUsageByKind(kind=kind, total_tokens=tokens, generation_count=count)
        for kind, tokens, count in db.execute(kq.order_by(LlmUsage.kind)).all()
    ]
    return LlmUsageSummary(total_tokens=total_tokens, generation_count=generation_count, by_kind=by_kind)

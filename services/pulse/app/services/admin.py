from datetime import date, datetime, time, timezone
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import LlmUsage
from app.schemas.admin import LlmUsageByKind, LlmUsageSummary
from app.services import credentials, llm_budget

SCOPE_SELF = "self"
SCOPE_DEPARTMENT = "department"
SCOPE_PLATFORM = "platform"

def _scope(db: Session, user: TokenClaims) -> tuple[str, list]:
    """Who is entitled to which figures, and the SQL that says so.

    The gate is llm_budget.may_see_figures, the same rule the budget messages already
    use: token counts are an accounting fact about somebody's key, so they belong to
    whoever is paying. Somebody running on the platform's key is not, and used to be able
    to read the whole organisation's spend anyway.

    Below that gate there are three answers and no fourth one. A platform admin sees
    everything, because the platform's money is theirs. An admin of a department sees
    what that department's key paid for, which is the figure that reconciles against
    their invoice, plus their own spend. Everyone else sees their own.

    A department admin does NOT see a member's personal-key spend: that is the member's
    money, and it is on nobody's departmental invoice.
    """
    if user.is_platform_admin:
        return SCOPE_PLATFORM, []
    credential = credentials.resolve_credential(db, user)
    if not llm_budget.may_see_figures(credential, is_platform_admin=False):
        raise HTTPException(
            status_code=403,
            detail=(
                "Token figures belong to whoever is paying for the calls. You are using "
                "the platform's key, so there is no bill of yours to show."
            ),
        )
    admin_dept_ids = [m.dept_id for m in user.memberships if m.role == "admin"]
    if admin_dept_ids:
        return SCOPE_DEPARTMENT, [or_(LlmUsage.dept_id.in_(admin_dept_ids), LlmUsage.user_id == user.user_id)]
    return SCOPE_SELF, [LlmUsage.user_id == user.user_id]

def llm_usage_summary(db: Session, user: TokenClaims, since: date | None = None) -> LlmUsageSummary:
    scope, where = _scope(db, user)
    if since is not None:
        where = where + [LlmUsage.created_at >= datetime.combine(since, time.min, tzinfo=timezone.utc)]

    q = select(func.coalesce(func.sum(LlmUsage.tokens), 0), func.count()).select_from(LlmUsage).where(*where)
    total_tokens, generation_count = db.execute(q).one()

    # Reports are no longer the only thing that spends tokens, so the totals alone
    # can't say which surface the bill came from.
    kq = select(LlmUsage.kind, func.coalesce(func.sum(LlmUsage.tokens), 0), func.count()).where(*where).group_by(LlmUsage.kind)
    by_kind = [
        LlmUsageByKind(kind=kind, total_tokens=tokens, generation_count=count)
        for kind, tokens, count in db.execute(kq.order_by(LlmUsage.kind)).all()
    ]
    return LlmUsageSummary(scope=scope, total_tokens=total_tokens, generation_count=generation_count, by_kind=by_kind)

"""Bring-your-own LLM keys: a company funds its own usage with a department key, an
individual can install a personal one, and the platform's env key is the fallback.

Two rules the rest of the service leans on:

  * The key is Fernet-encrypted with the same mechanism protecting GitHub tokens
    (app/crypto.py), is never logged, and never leaves here in a response. `last_four`
    is what a UI gets.
  * `bypass_token_cap` only means anything on a key the caller pays for. The platform's
    env key is never bypassable — see llm_budget.check_budget.
"""
import logging
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app import crypto
from app.config import settings
from app.models import (
    PROVIDER_ANTHROPIC, PROVIDER_OPENAI, SCOPE_DEPARTMENT, SCOPE_PLATFORM, SCOPE_USER,
    ApiCredential, TokenBudget,
)

logger = logging.getLogger(__name__)

SOURCE_USER = "user"
SOURCE_DEPARTMENT = "department"
SOURCE_PLATFORM = "platform"
SOURCE_NONE = "none"

# How many trailing characters are kept in the clear for display. Four is what card and
# key UIs everywhere use, and short enough to be useless on its own.
LAST_FOUR_CHARS = 4

# What an absent budget row means at the top of the chain. Kept as a name so the one
# place the environment variable is still read is obvious.
SOURCE_PLATFORM_DEFAULT = "platform_default"

class InvalidApiKeyError(Exception):
    """The provider rejected the key. A stored key that does not work is worse than no
    key at all, because nothing fails until the next generation."""

@dataclass
class ResolvedCredential:
    source: str
    provider: str
    key: str
    model: str | None
    bypass_token_cap: bool
    credential_id: int | None = None
    # Which department's money this is, on a department-scoped key and nowhere else. The
    # ledger stamps it on every row so a department admin can be shown the spend that
    # reconciles against their own invoice.
    dept_id: int | None = None

def _preferred_providers(provider: str | None) -> tuple[str, ...]:
    """Which providers are allowed for this call, best first. A pinned AI_PROVIDER is
    pinned here too, for the reason ai_provider.active_provider gives."""
    if provider is not None:
        return (provider,)
    pinned = (settings.AI_PROVIDER or "auto").strip().lower()
    if pinned in (PROVIDER_ANTHROPIC, PROVIDER_OPENAI):
        return (pinned,)
    return (PROVIDER_ANTHROPIC, PROVIDER_OPENAI)

def _platform_key(provider: str) -> str:
    return settings.ANTHROPIC_API_KEY if provider == PROVIDER_ANTHROPIC else settings.LLM_API_KEY

def _platform_model(provider: str) -> str:
    return settings.ANTHROPIC_MODEL if provider == PROVIDER_ANTHROPIC else settings.LLM_MODEL

def _row_to_resolved(row: ApiCredential, source: str) -> ResolvedCredential:
    return ResolvedCredential(
        source=source,
        provider=row.provider,
        key=crypto.decrypt(row.key_encrypted),
        model=row.model,
        bypass_token_cap=bool(row.bypass_token_cap),
        credential_id=row.id,
        dept_id=row.dept_id if source == SOURCE_DEPARTMENT else None,
    )

def paying_dept_id(credential: "ResolvedCredential | None") -> int | None:
    """The department to bill this call to, which is only ever a department key. A user's
    own key is their money and the platform's key is the platform's; neither belongs on a
    department's invoice, so both stamp null."""
    if credential is None or credential.source != SOURCE_DEPARTMENT:
        return None
    return credential.dept_id

def _find(db: Session, *, scope: str, provider: str, owner_user_id: int | None = None, dept_id: int | None = None) -> ApiCredential | None:
    owner_match = ApiCredential.owner_user_id.is_(None) if owner_user_id is None else ApiCredential.owner_user_id == owner_user_id
    dept_match = ApiCredential.dept_id.is_(None) if dept_id is None else ApiCredential.dept_id == dept_id
    return db.scalar(
        select(ApiCredential).where(
            ApiCredential.scope == scope,
            ApiCredential.provider == provider,
            owner_match,
            dept_match,
        )
    )

def resolve_credential(db: Session, user: TokenClaims, *, provider: str | None = None) -> ResolvedCredential | None:
    """user -> department -> platform env. Scope beats provider preference: a user who
    installed their own key pays with it even when the platform prefers the other
    provider."""
    return resolve_for_user_id(db, user.user_id, dept_ids=user.dept_ids, provider=provider)

def resolve_for_user_id(db: Session, user_id: int, *, dept_ids: "tuple[int, ...] | list[int]" = (), provider: str | None = None) -> ResolvedCredential | None:
    """The same resolution without a token to read it from — a Celery task holds a user
    id and nothing else. Department keys are only reachable when the caller can say which
    departments the user belongs to, because that fact lives in identity, not here; with
    no memberships the user's own key and the platform env key are what is left.
    """
    providers = _preferred_providers(provider)

    for prov in providers:
        row = _find(db, scope=SCOPE_USER, provider=prov, owner_user_id=user_id)
        if row is not None:
            return _row_to_resolved(row, SOURCE_USER)

    for dept_id in dept_ids:
        for prov in providers:
            row = _find(db, scope=SCOPE_DEPARTMENT, provider=prov, dept_id=dept_id)
            if row is not None:
                return _row_to_resolved(row, SOURCE_DEPARTMENT)

    for prov in providers:
        if _platform_key(prov):
            # bypass_token_cap is hardcoded False, not read from anywhere: this is the
            # platform's money, and the daily cap is the only thing protecting it.
            return ResolvedCredential(
                source=SOURCE_PLATFORM,
                provider=prov,
                key=_platform_key(prov),
                model=_platform_model(prov),
                bypass_token_cap=False,
            )
    return None

def probe_key(provider: str, key: str) -> None:
    """One cheap live call before a key is stored. Listing models costs no tokens and
    still proves the key is accepted.

    The seam tests replace: everything above it is pure, and this is the only part that
    touches the network."""
    try:
        if provider == PROVIDER_ANTHROPIC:
            import anthropic

            anthropic.Anthropic(api_key=key, timeout=settings.ANTHROPIC_TIMEOUT_SECONDS).models.list(limit=1)
        else:
            from openai import OpenAI

            OpenAI(api_key=key, timeout=settings.LLM_TIMEOUT_SECONDS).models.list()
    except Exception as exc:
        # The message names the provider and the failure class only. The key is not
        # interpolated anywhere, and provider exceptions carry the request they were
        # made with.
        logger.warning("api credential probe rejected a %s key: %s", provider, type(exc).__name__)
        raise InvalidApiKeyError(f"{provider} rejected this key. Check it and try again.") from exc

def _require_may_write(user: TokenClaims, *, scope: str, owner_user_id: int | None, dept_id: int | None) -> None:
    if user.is_platform_admin:
        return
    if scope == SCOPE_USER:
        if owner_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="You can only set your own API key")
        return
    if user.role_in(dept_id) != "admin":
        raise HTTPException(status_code=403, detail="Requires a platform admin or an admin of that department")

def _can_read(user: TokenClaims, row: ApiCredential) -> bool:
    if user.is_platform_admin:
        return True
    if row.scope == SCOPE_USER:
        return row.owner_user_id == user.user_id
    return row.dept_id in user.dept_ids

def list_credentials(db: Session, user: TokenClaims) -> list[ApiCredential]:
    """The caller's own, plus the department keys of departments they belong to — a
    department key spends on their behalf, so they get to see that it exists."""
    if user.is_platform_admin:
        rows = db.scalars(select(ApiCredential).order_by(ApiCredential.scope, ApiCredential.id))
        return list(rows)
    scope = [ApiCredential.owner_user_id == user.user_id]
    if user.dept_ids:
        scope.append(ApiCredential.dept_id.in_(user.dept_ids))
    rows = db.scalars(select(ApiCredential).where(or_(*scope)).order_by(ApiCredential.scope, ApiCredential.id))
    return list(rows)

def upsert_credential(db: Session, user: TokenClaims, payload) -> ApiCredential:
    scope = payload.scope
    dept_id = payload.dept_id if scope == SCOPE_DEPARTMENT else None
    owner_user_id = (payload.owner_user_id or user.user_id) if scope == SCOPE_USER else None
    if scope == SCOPE_DEPARTMENT and dept_id is None:
        raise HTTPException(status_code=422, detail="A department key needs a dept_id")
    _require_may_write(user, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id)

    row = _find(db, scope=scope, provider=payload.provider, owner_user_id=owner_user_id, dept_id=dept_id)
    key = payload.key.strip() if payload.key is not None else None
    if key is None and row is None:
        raise HTTPException(status_code=422, detail="An API key is required the first time you set one")

    # Only probe what was actually supplied. Editing the cap flag or the model on an
    # existing row must not cost a network round trip, and must not fail because the
    # provider happens to be unreachable right now.
    if key is not None:
        try:
            probe_key(payload.provider, key)
        except InvalidApiKeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    if row is None:
        row = ApiCredential(
            scope=scope,
            owner_user_id=owner_user_id,
            dept_id=dept_id,
            provider=payload.provider,
            created_by_user_id=user.user_id,
        )
        db.add(row)
    if key is not None:
        row.key_encrypted = crypto.encrypt(key)
        row.last_four = key[-LAST_FOUR_CHARS:]
    row.model = payload.model
    row.bypass_token_cap = bool(payload.bypass_token_cap)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A key for that provider is already set at this scope")
    db.refresh(row)
    logger.info("api credential set: scope=%s owner=%s dept=%s provider=%s by=%s", scope, owner_user_id, dept_id, payload.provider, user.user_id)
    return row

def delete_credential(db: Session, user: TokenClaims, credential_id: int) -> None:
    row = db.get(ApiCredential, credential_id)
    if row is None or not _can_read(user, row):
        raise HTTPException(status_code=404, detail="API key not found")
    _require_may_write(user, scope=row.scope, owner_user_id=row.owner_user_id, dept_id=row.dept_id)
    db.delete(row)
    db.commit()

def effective_credential(db: Session, user: TokenClaims, *, provider: str | None = None) -> dict:
    """Which key a generation right now would spend, and whose it is. Never the key."""
    resolved = resolve_credential(db, user, provider=provider)
    if resolved is None:
        return {"source": SOURCE_NONE, "provider": None, "model": None, "bypass_token_cap": False}
    return {
        "source": resolved.source,
        "provider": resolved.provider,
        "model": resolved.model or _platform_model(resolved.provider),
        "bypass_token_cap": resolved.bypass_token_cap,
    }


# ---------------------------------------------------------------------------
# Daily token allowances.
#
# Same three levels as a key and resolved in the same order, because the two answer
# halves of one question: whose money, and how much of it. The rule tying them together
# is that you may only relax a limit on spend you are paying for. Lowering one is always
# allowed: nobody needs permission to spend less of somebody else's money.
# ---------------------------------------------------------------------------

def _find_budget(db: Session, *, scope: str, owner_user_id: int | None = None, dept_id: int | None = None) -> TokenBudget | None:
    owner_match = TokenBudget.owner_user_id.is_(None) if owner_user_id is None else TokenBudget.owner_user_id == owner_user_id
    dept_match = TokenBudget.dept_id.is_(None) if dept_id is None else TokenBudget.dept_id == dept_id
    return db.scalar(select(TokenBudget).where(TokenBudget.scope == scope, owner_match, dept_match))

def _platform_cap(db: Session) -> tuple[int, str]:
    row = _find_budget(db, scope=SCOPE_PLATFORM)
    if row is not None:
        return int(row.daily_token_cap), SOURCE_PLATFORM
    return int(settings.LLM_DAILY_TOKEN_CAP_PER_USER), SOURCE_PLATFORM_DEFAULT

def resolve_cap(db: Session, user_id: int, *, dept_ids: "tuple[int, ...] | list[int]" = ()) -> tuple[int, str]:
    """The allowance in force for this user right now, and where it came from.

    Department rows are only reachable when the caller can say which departments the user
    belongs to, for the same reason resolve_for_user_id gives: that fact lives in
    identity and only a token carries it. A Celery task holding a bare user id therefore
    sees the user's own row and the platform's, which is the safe direction to miss in.
    """
    row = _find_budget(db, scope=SCOPE_USER, owner_user_id=user_id)
    if row is not None:
        return int(row.daily_token_cap), SOURCE_USER
    for dept_id in dept_ids:
        row = _find_budget(db, scope=SCOPE_DEPARTMENT, dept_id=dept_id)
        if row is not None:
            return int(row.daily_token_cap), SOURCE_DEPARTMENT
    return _platform_cap(db)

def _inherited_cap(db: Session, *, scope: str, owner_user_id: int | None, dept_id: int | None, dept_ids: "tuple[int, ...] | list[int]") -> tuple[int, str]:
    """What the cap would be with this row absent. That is the ceiling a raise has to
    clear, so it is computed by skipping the level being written."""
    if scope == SCOPE_PLATFORM:
        return int(settings.LLM_DAILY_TOKEN_CAP_PER_USER), SOURCE_PLATFORM_DEFAULT
    if scope == SCOPE_DEPARTMENT:
        return _platform_cap(db)
    for other in dept_ids:
        row = _find_budget(db, scope=SCOPE_DEPARTMENT, dept_id=other)
        if row is not None:
            return int(row.daily_token_cap), SOURCE_DEPARTMENT
    return _platform_cap(db)

def is_more_permissive(requested: int, inherited: int) -> bool:
    """Whether `requested` allows more spending than `inherited`. Zero is unlimited, so
    it beats every number, and nothing beats it."""
    if inherited <= 0:
        return False
    if requested <= 0:
        return True
    return requested > inherited

def _pays_for_own_spend(db: Session, *, scope: str, owner_user_id: int | None, dept_id: int | None) -> bool:
    """Whether whoever this row governs is funding the calls it would allow.

    A department qualifies when it has installed a key of its own. A user qualifies only
    when their OWN key is what resolution picks: a department key sitting above them is
    the department's money, not theirs, and raising their ceiling would be spending it.
    """
    if scope == SCOPE_DEPARTMENT:
        return any(_find(db, scope=SCOPE_DEPARTMENT, provider=prov, dept_id=dept_id) is not None
                   for prov in (PROVIDER_OPENAI, PROVIDER_ANTHROPIC))
    # dept_ids is deliberately empty: a user key wins resolution outright, so leaving
    # department keys out cannot turn a "no" into a "yes".
    resolved = resolve_for_user_id(db, owner_user_id)
    return resolved is not None and resolved.source == SOURCE_USER

def _require_may_raise(db: Session, user: TokenClaims, *, scope: str, owner_user_id: int | None, dept_id: int | None, requested: int, inherited: int, inherited_source: str) -> None:
    if not is_more_permissive(requested, inherited):
        return
    # The platform's key is the platform admin's own spend, so raising anything is theirs
    # to do. Everyone else has to be paying.
    if user.is_platform_admin or scope == SCOPE_PLATFORM:
        return
    if _pays_for_own_spend(db, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id):
        return
    ceiling = "unlimited" if inherited <= 0 else f"{inherited:,} tokens a day"
    whose = "This department has" if scope == SCOPE_DEPARTMENT else "You have"
    logger.warning(
        "token budget raise refused: scope=%s owner=%s dept=%s requested=%s inherited=%s by=%s",
        scope, owner_user_id, dept_id, requested, inherited, user.user_id,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            f"The allowance you inherit is {ceiling}, and raising it means spending more "
            f"of somebody else's money. {whose} no API key of your own, so this allowance "
            "can only be lowered. Add a key and the ceiling is yours to set."
        ),
    )

def list_budgets(db: Session, user: TokenClaims) -> list[TokenBudget]:
    if user.is_platform_admin:
        return list(db.scalars(select(TokenBudget).order_by(TokenBudget.scope, TokenBudget.id)))
    scope = [TokenBudget.owner_user_id == user.user_id, TokenBudget.scope == SCOPE_PLATFORM]
    if user.dept_ids:
        scope.append(TokenBudget.dept_id.in_(user.dept_ids))
    return list(db.scalars(select(TokenBudget).where(or_(*scope)).order_by(TokenBudget.scope, TokenBudget.id)))

def upsert_budget(db: Session, user: TokenClaims, payload) -> TokenBudget:
    scope = payload.scope
    dept_id = payload.dept_id if scope == SCOPE_DEPARTMENT else None
    owner_user_id = (payload.owner_user_id or user.user_id) if scope == SCOPE_USER else None
    if scope == SCOPE_DEPARTMENT and dept_id is None:
        raise HTTPException(status_code=422, detail="A department allowance needs a dept_id")
    if scope == SCOPE_PLATFORM and not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Only a platform admin can set the platform allowance")
    if scope != SCOPE_PLATFORM:
        _require_may_write(user, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id)

    inherited, inherited_source = _inherited_cap(db, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id, dept_ids=user.dept_ids)
    _require_may_raise(
        db, user, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id,
        requested=payload.daily_token_cap, inherited=inherited, inherited_source=inherited_source,
    )

    row = _find_budget(db, scope=scope, owner_user_id=owner_user_id, dept_id=dept_id)
    if row is None:
        row = TokenBudget(scope=scope, owner_user_id=owner_user_id, dept_id=dept_id, created_by_user_id=user.user_id)
        db.add(row)
    row.daily_token_cap = payload.daily_token_cap
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An allowance is already set at this scope")
    db.refresh(row)
    logger.info("token budget set: scope=%s owner=%s dept=%s cap=%s by=%s", scope, owner_user_id, dept_id, row.daily_token_cap, user.user_id)
    return row

def delete_budget(db: Session, user: TokenClaims, budget_id: int) -> None:
    """Removing a row restores whatever it was overriding, which can only tighten or
    leave the allowance alone, so it needs no raise check."""
    row = db.get(TokenBudget, budget_id)
    if row is None or not _can_read_budget(user, row):
        raise HTTPException(status_code=404, detail="Allowance not found")
    if row.scope == SCOPE_PLATFORM:
        if not user.is_platform_admin:
            raise HTTPException(status_code=403, detail="Only a platform admin can set the platform allowance")
    else:
        _require_may_write(user, scope=row.scope, owner_user_id=row.owner_user_id, dept_id=row.dept_id)
    db.delete(row)
    db.commit()

def _can_read_budget(user: TokenClaims, row: TokenBudget) -> bool:
    if user.is_platform_admin or row.scope == SCOPE_PLATFORM:
        return True
    if row.scope == SCOPE_USER:
        return row.owner_user_id == user.user_id
    return row.dept_id in user.dept_ids

def effective_budget(db: Session, user: TokenClaims) -> dict:
    """The cap a call right now would be measured against, where it came from, and how
    much of today is gone. The UI says all three so nobody has to guess which level is
    biting.

    `may_raise` and `show_figures` answer different questions and diverge for a user
    under a department key: the department's money is not theirs to spend more of, but it
    is being spent on them, so the figures are theirs to see."""
    from app.services import llm_budget, platform_settings

    dept_admins_see_platform_figures = platform_settings.get_bool(db, platform_settings.DEPT_ADMINS_SEE_PLATFORM_FIGURES)
    cap, source = resolve_cap(db, user.user_id, dept_ids=user.dept_ids)
    inherited, inherited_source = _inherited_cap(db, scope=SCOPE_USER, owner_user_id=user.user_id, dept_id=None, dept_ids=user.dept_ids)
    used = llm_budget.tokens_used_today(db, user.user_id)
    return {
        "daily_token_cap": cap,
        "source": source,
        "inherited_cap": inherited,
        "inherited_source": inherited_source,
        "tokens_used_today": used,
        "may_raise": user.is_platform_admin or _pays_for_own_spend(db, scope=SCOPE_USER, owner_user_id=user.user_id, dept_id=None),
        "show_figures": llm_budget.may_see_figures(
            resolve_credential(db, user),
            is_platform_admin=user.is_platform_admin,
            is_dept_admin=any(m.role == "admin" for m in user.memberships),
            dept_admins_see_platform_figures=dept_admins_see_platform_figures,
        ),
        "dept_admins_see_platform_figures": dept_admins_see_platform_figures,
    }

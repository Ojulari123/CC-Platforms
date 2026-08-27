"""Platform-wide switches, read by anything and written only by a platform admin.

One store rather than one table per switch: these are single facts about the whole
installation, and each of them wants the same three things: a default when no row
exists, a typed read, and a write nobody but a platform admin can make.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import PlatformSetting

# Whether a department admin may read their department's token figures while the
# platform's key is the one paying. Off means llm_budget.may_see_figures keeps refusing
# them, which is what it did before this setting existed.
DEPT_ADMINS_SEE_PLATFORM_FIGURES = "dept_admins_see_platform_figures"

_DEFAULTS = {DEPT_ADMINS_SEE_PLATFORM_FIGURES: False}

_TRUE = {"true", "1", "yes", "on"}

def get_bool(db: Session, key: str) -> bool:
    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    if row is None:
        return _DEFAULTS[key]
    return row.value.strip().lower() in _TRUE

def set_bool(db: Session, user: TokenClaims, key: str, value: bool) -> bool:
    """A platform setting is the platform's to change, so nothing below a platform admin
    may write one. A department admin turning on their own visibility would be marking
    their own homework."""
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Only a platform admin can change a platform setting")
    if key not in _DEFAULTS:
        raise HTTPException(status_code=404, detail="No such platform setting")
    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
    if row is None:
        row = PlatformSetting(key=key, value="", updated_by_user_id=user.user_id)
        db.add(row)
    row.value = "true" if value else "false"
    row.updated_by_user_id = user.user_id
    db.commit()
    return value

def all_settings(db: Session) -> dict:
    return {key: get_bool(db, key) for key in _DEFAULTS}

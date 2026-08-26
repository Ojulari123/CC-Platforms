from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

CredentialScope = Literal["user", "department"]
CredentialProvider = Literal["openai", "anthropic"]
# One level wider than a key: there is no platform API credential row, but the platform
# allowance is a row so an admin can move it without a redeploy.
BudgetScope = Literal["user", "department", "platform"]
CapSource = Literal["user", "department", "platform", "platform_default"]

class CredentialUpsert(BaseModel):
    scope: CredentialScope
    provider: CredentialProvider
    # Omitted means "leave the stored key alone" — that is how `bypass_token_cap` and
    # `model` get edited without the caller having to hand the secret over again. The
    # service rejects an absent key when there is no row to update.
    key: str | None = Field(default=None, min_length=8, max_length=500)
    model: str | None = Field(default=None, max_length=100)
    bypass_token_cap: bool = False
    dept_id: int | None = None
    # Only a platform admin may name someone else here; the service enforces that.
    # Absent means the caller.
    owner_user_id: int | None = None

    @field_validator("key")
    @classmethod
    def _no_blank_keys(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip()
        if not key:
            raise ValueError("An API key can't be empty")
        return key

class CredentialResponse(BaseModel):
    """No `key` field, by construction rather than by remembering to exclude it."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: str
    owner_user_id: int | None
    dept_id: int | None
    provider: str
    model: str | None
    last_four: str
    bypass_token_cap: bool
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

class CredentialList(BaseModel):
    items: list[CredentialResponse]

class EffectiveCredentialResponse(BaseModel):
    source: Literal["user", "department", "platform", "none"]
    provider: str | None
    model: str | None
    bypass_token_cap: bool

class BudgetUpsert(BaseModel):
    scope: BudgetScope
    # 0 is unlimited, matching LLM_DAILY_TOKEN_CAP_PER_USER. The upper bound is a typo
    # guard, not a policy: nobody means to type ten more zeros.
    daily_token_cap: int = Field(ge=0, le=1_000_000_000)
    dept_id: int | None = None
    # Only a platform admin may name someone else here; the service enforces that.
    # Absent means the caller.
    owner_user_id: int | None = None

class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: str
    owner_user_id: int | None
    dept_id: int | None
    daily_token_cap: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

class BudgetList(BaseModel):
    items: list[BudgetResponse]

class EffectiveBudgetResponse(BaseModel):
    """What a call right now is measured against, and what it would fall back to. Both,
    so the UI can say which level is biting rather than showing a number with no story."""
    daily_token_cap: int
    source: CapSource
    inherited_cap: int
    inherited_source: CapSource
    tokens_used_today: int
    may_raise: bool
    # Whether the figures above mean anything to this person, which is a different
    # question from whether the cap is theirs to raise. Same rule the 429 messages use.
    show_figures: bool

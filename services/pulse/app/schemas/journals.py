from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.users import UserRef

class JournalCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def _no_blank_entries(cls, value: str) -> str:
        # min_length runs before this, so whitespace-only is the case left to catch.
        body = value.strip()
        if not body:
            raise ValueError("A journal entry can't be empty")
        return body

class JournalUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def _no_blank_entries(cls, value: str) -> str:
        body = value.strip()
        if not body:
            raise ValueError("A journal entry can't be empty")
        return body

class JournalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_id: int
    author_user_id: int
    author: UserRef | None = None
    body: str
    created_at: datetime
    edited_at: datetime | None

class RollupRequest(BaseModel):
    persona_id: int | None = None

class RollupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_id: int
    summary: str
    entry_count: int
    covers_from: datetime | None
    covers_to: datetime | None
    generated_by_user_id: int
    generated_by: UserRef | None = None
    model: str | None
    prompt_version: str | None
    created_at: datetime

class LatestRollupResponse(BaseModel):
    """A wrapper rather than a nullable body, matching how every other collection-shaped
    answer here is wrapped (Page.items, CredentialList.items). It also leaves somewhere to
    put a second field later without changing the shape again."""
    rollup: RollupResponse | None = None

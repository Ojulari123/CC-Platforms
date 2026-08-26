from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

PersonaLength = Literal["brief", "standard", "detailed"]
PersonaAudience = Literal["executive", "manager", "engineer"]
PersonaTechnicalDepth = Literal["low", "medium", "high"]
PersonaFormality = Literal["casual", "neutral", "formal"]

class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    length: PersonaLength = "standard"
    audience: PersonaAudience = "manager"
    technical_depth: PersonaTechnicalDepth = "medium"
    formality: PersonaFormality = "neutral"
    instructions: str | None = Field(default=None, max_length=2000)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _no_blank_names(cls, value: str) -> str:
        # min_length runs before this, so whitespace-only is the case left to catch.
        name = value.strip()
        if not name:
            raise ValueError("A persona needs a name")
        return name

class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    length: PersonaLength | None = None
    audience: PersonaAudience | None = None
    technical_depth: PersonaTechnicalDepth | None = None
    formality: PersonaFormality | None = None
    instructions: str | None = Field(default=None, max_length=2000)
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def _no_blank_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("A persona needs a name")
        return name

class PersonaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int | None
    name: str
    length: str
    audience: str
    technical_depth: str
    formality: str
    instructions: str | None
    is_default: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

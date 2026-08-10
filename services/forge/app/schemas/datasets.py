import json
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int | None
    is_sample: bool
    name: str
    original_filename: str | None
    columns: list[str]
    row_count: int
    created_at: datetime

    @field_validator("columns", mode="before")
    @classmethod
    def _parse_columns(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

class DatasetSummary(BaseModel):
    owned_count: int
    sample_count: int
    recent: list[DatasetResponse]

class DatasetPreview(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    row_count: int
    truncated: bool

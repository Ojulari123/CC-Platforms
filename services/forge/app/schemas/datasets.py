import json
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int | None
    is_sample: bool
    kind: str
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

class ImageEntry(BaseModel):
    name: str
    # Empty for a loose image that was not filed under a class folder.
    cls: str = Field(alias="class")
    bytes: int

class ImageDatasetManifest(BaseModel):
    classes: list[str]
    counts: dict[str, int]
    images: list[ImageEntry]
    total: int
    # Said here as well as in the run result, so the weakness is visible before a learner
    # spends time on a workflow rather than only after the score comes back.
    method_note: str

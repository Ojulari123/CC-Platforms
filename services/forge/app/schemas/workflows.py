import json
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

class StepIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)

class StepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    kind: str
    params: dict[str, Any]

    @field_validator("params", mode="before")
    @classmethod
    def _parse_params(cls, v):
        return json.loads(v) if isinstance(v, str) else v

class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    dataset_id: int | None = None
    steps: list[StepIn]

class StepsUpdate(BaseModel):
    steps: list[StepIn]

class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int
    name: str
    kind: str
    dataset_id: int | None
    steps: list[StepResponse]
    created_at: datetime

class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    status: str
    error: str | None
    metrics: dict[str, Any] | None
    result: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime

    @field_validator("metrics", "result", mode="before")
    @classmethod
    def _parse_json(cls, v):
        return json.loads(v) if isinstance(v, str) else v

class GeneratedCode(BaseModel):
    filename: str
    language: str
    code: str

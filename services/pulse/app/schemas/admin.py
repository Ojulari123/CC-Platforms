from pydantic import BaseModel

class LlmUsageByKind(BaseModel):
    kind: str
    total_tokens: int
    generation_count: int

class LlmUsageSummary(BaseModel):
    total_tokens: int
    generation_count: int
    by_kind: list[LlmUsageByKind] = []

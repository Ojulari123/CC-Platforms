from pydantic import BaseModel

class LlmUsageByKind(BaseModel):
    kind: str
    total_tokens: int
    generation_count: int

class LlmUsageSummary(BaseModel):
    # What the figures below cover: "self", "department" or "platform". Sent because the
    # same endpoint now answers three different questions and a total with no scope on it
    # reads as the organisation's.
    scope: str
    total_tokens: int
    generation_count: int
    by_kind: list[LlmUsageByKind] = []

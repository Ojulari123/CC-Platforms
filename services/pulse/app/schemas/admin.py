from pydantic import BaseModel

class LlmUsageSummary(BaseModel):
    total_tokens: int
    generation_count: int

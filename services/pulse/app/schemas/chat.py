from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.chat import MAX_CONTENT_CHARS

class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    # Absent or empty means every ready index the caller owns. The list is what a
    # narrowed scope looks like, not a requirement.
    indexed_repo_ids: list[int] | None = None

    @field_validator("content")
    @classmethod
    def _no_blank_questions(cls, value: str) -> str:
        # min_length runs before this, so whitespace-only is the case left to catch.
        content = value.strip()
        if not content:
            raise ValueError("A question can't be empty")
        return content

class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Null once the index it came from has been deleted; the rest of the row still says
    # which repository, file and lines the answer was grounded in. See models.ChatCitation.
    indexed_repo_id: int | None
    full_name: str
    path: str
    start_line: int
    end_line: int
    snippet: str

class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    citations: list[CitationResponse] = []
    model: str | None
    tokens: int | None
    created_at: datetime

class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime

class ConversationDetailResponse(ConversationResponse):
    messages: list[ChatMessageResponse] = []

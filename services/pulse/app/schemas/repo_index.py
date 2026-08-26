from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.repo_index import is_valid_full_name

class IndexRequest(BaseModel):
    full_name: str = Field(min_length=3, max_length=140)

    @field_validator("full_name")
    @classmethod
    def _looks_like_a_repository(cls, value: str) -> str:
        # Rejected here as well as in the service: this value ends up inside a GitHub URL,
        # and the two entry points to that URL are this schema and the Celery task, which
        # never sees a request body.
        full_name = value.strip()
        if not is_valid_full_name(full_name):
            raise ValueError("Give the repository as owner/name, for example cyphercrescent/pulse")
        return full_name

class IndexedRepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_id: int | None
    full_name: str
    is_public: bool
    owner_user_id: int
    commit_sha: str | None
    status: str
    detail: str | None
    file_count: int
    chunk_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

class GitHubIndexStatus(BaseModel):
    connected: bool
    has_repo_scope: bool
    # True only for an account that is connected but whose token predates the widened
    # scopes. Not connected at all is a different problem with a different fix, so it
    # reads False here and `detail` stays empty.
    reconnect_required: bool = False
    detail: str | None = None

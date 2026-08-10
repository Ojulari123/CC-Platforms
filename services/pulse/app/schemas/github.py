from datetime import datetime
from pydantic import BaseModel, ConfigDict

class GitHubConnectResponse(BaseModel):
    authorize_url: str

class GitHubAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    github_user_id: int
    github_login: str
    scopes: str | None
    connected_at: datetime

class SyncRunResponse(BaseModel):
    """One repo's turn in one sync pass. `detail` carries the per-kind counts on
    success and the reason on anything else — including, when rate-limited, when
    GitHub says we can resume."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_id: int | None
    repo_full_name: str | None = None  # denormalised so a list renders without a second call
    status: str
    detail: str | None
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, run) -> "SyncRunResponse":
        item = cls.model_validate(run)
        item.repo_full_name = run.repository.full_name if run.repository is not None else None
        return item

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

class ConnectedAccountResponse(BaseModel):
    """A wrapper rather than a nullable body, for the same reason LatestRollupResponse is
    one: not having connected GitHub yet is a normal state, and serving it as a 404 put a
    stack trace in the console of every user who had not."""
    account: GitHubAccountResponse | None = None

class SyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_id: int | None
    repo_full_name: str | None = None
    status: str
    detail: str | None
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, run) -> "SyncRunResponse":
        item = cls.model_validate(run)
        item.repo_full_name = run.repository.full_name if run.repository is not None else None
        return item

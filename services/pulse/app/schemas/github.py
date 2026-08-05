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

from datetime import datetime
from pydantic import BaseModel, ConfigDict

class GitHubConnectResponse(BaseModel):
    """Where to send the browser to authorize. The frontend performs the redirect
    (for now, in dev, you open this URL yourself)."""
    authorize_url: str

class GitHubAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    github_user_id: int
    github_login: str
    scopes: str | None
    connected_at: datetime

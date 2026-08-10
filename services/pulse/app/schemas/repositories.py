from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.schemas.users import UserRef

class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_repo_id: int
    full_name: str
    owner: str
    name: str
    private: bool
    is_tracked: bool
    default_branch: str | None
    dept_id: int | None
    lead_user_id: int | None
    lead: UserRef | None = None  # filled from identity; null if it can't be resolved
    deputy_user_id: int | None
    deputy: UserRef | None = None
    last_synced_at: datetime | None

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.users import UserRef

class RepositoryDepartmentRequest(BaseModel):
    repo_ids: list[int] = Field(min_length=1, max_length=200)

class ApproverCandidate(BaseModel):
    user_id: int
    person: UserRef | None = None
    has_activity: bool
    is_lead: bool
    is_deputy: bool

class ApproverCandidateList(BaseModel):
    items: list[ApproverCandidate]

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
    lead: UserRef | None = None
    deputy_user_id: int | None
    deputy: UserRef | None = None
    last_synced_at: datetime | None

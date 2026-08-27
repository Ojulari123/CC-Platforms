from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.schemas.repositories import (
    ApproverCandidate, ApproverCandidateList, RepositoryDepartmentRequest, RepositoryResponse,
)
from app.services import people, repositories as repo_service

router = APIRouter(prefix="/github/repositories", tags=["repositories"])

_APPROVERS = (("lead_user_id", "lead"), ("deputy_user_id", "deputy"))

def _named(rows) -> list[RepositoryResponse]:
    items = [RepositoryResponse.model_validate(r) for r in rows]
    people.attach_names(items, *_APPROVERS)
    return items

@router.get("", response_model=Page[RepositoryResponse])
def list_repositories(tracked_only: bool = Query(default=False), page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[RepositoryResponse]:
    repos, total = repo_service.list_repositories(db, user, tracked_only=tracked_only, limit=page.limit, offset=page.offset)
    return Page.of(_named(repos), total=total, params=page)

# Declared before /{repo_id}: a literal segment has to be matched first, or "unfiled"
# is read as a repo id.
@router.get("/unfiled", response_model=Page[RepositoryResponse])
def list_unfiled_repositories(page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[RepositoryResponse]:
    repos, total = repo_service.unfiled_repositories(db, user, limit=page.limit, offset=page.offset)
    return Page.of(_named(repos), total=total, params=page)

@router.put("/department/{dept_id}", response_model=list[RepositoryResponse])
def set_departments(dept_id: int, payload: RepositoryDepartmentRequest, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> list[RepositoryResponse]:
    return _named(repo_service.set_departments(db, user, payload.repo_ids, dept_id))

@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.get_repository(db, user, repo_id)])[0]

@router.put("/{repo_id}/department/{dept_id}", response_model=RepositoryResponse)
def set_department(repo_id: int, dept_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_department(db, user, repo_id, dept_id)])[0]

@router.put("/{repo_id}/tracked", response_model=RepositoryResponse)
def track_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_tracked(db, user, repo_id, True)])[0]

@router.delete("/{repo_id}/tracked", response_model=RepositoryResponse)
def untrack_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_tracked(db, user, repo_id, False)])[0]

@router.get("/{repo_id}/approver-candidates", response_model=ApproverCandidateList)
def list_approver_candidates(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ApproverCandidateList:
    repo, ids, worked_in = repo_service.approver_candidates(db, user, repo_id)
    items = [
        ApproverCandidate(
            user_id=uid,
            has_activity=uid in worked_in,
            is_lead=uid == repo.lead_user_id,
            is_deputy=uid == repo.deputy_user_id,
        )
        for uid in ids
    ]
    people.attach_names(items, ("user_id", "person"))
    return ApproverCandidateList(items=items)

@router.put("/{repo_id}/lead/{user_id}", response_model=RepositoryResponse)
def set_lead(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_lead(db, user, repo_id, user_id)])[0]

@router.delete("/{repo_id}/lead", response_model=RepositoryResponse)
def clear_lead(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_lead(db, user, repo_id, None)])[0]

@router.put("/{repo_id}/deputy/{user_id}", response_model=RepositoryResponse)
def set_deputy(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_deputy(db, user, repo_id, user_id)])[0]

@router.delete("/{repo_id}/deputy", response_model=RepositoryResponse)
def clear_deputy(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_deputy(db, user, repo_id, None)])[0]

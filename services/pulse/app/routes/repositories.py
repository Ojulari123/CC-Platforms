from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.schemas.repositories import RepositoryResponse
from app.services import people, repositories as repo_service

router = APIRouter(prefix="/github/repositories", tags=["repositories"])

_APPROVERS = (("lead_user_id", "lead"), ("deputy_user_id", "deputy"))

def _named(rows) -> list[RepositoryResponse]:
    """Validate rows and resolve every lead/deputy across them in one identity call.
    Names are decoration — unresolvable ids stay null."""
    items = [RepositoryResponse.model_validate(r) for r in rows]
    people.attach_names(items, *_APPROVERS)
    return items

@router.get("", response_model=Page[RepositoryResponse])
def list_repositories(tracked_only: bool = Query(default=False), page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[RepositoryResponse]:
    repos, total = repo_service.list_repositories(db, user, tracked_only=tracked_only, limit=page.limit, offset=page.offset)
    return Page.of(_named(repos), total=total, params=page)

@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """A repo the caller has no relationship to reads as 404, not 403 — the existence
    of a private repo is itself worth not leaking."""
    return _named([repo_service.get_repository(db, user, repo_id)])[0]

@router.put("/{repo_id}/department/{dept_id}", response_model=RepositoryResponse)
def set_department(repo_id: int, dept_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_department(db, user, repo_id, dept_id)])[0]

@router.put("/{repo_id}/tracked", response_model=RepositoryResponse)
def track_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Resume syncing this repo. Idempotent."""
    return _named([repo_service.set_tracked(db, user, repo_id, True)])[0]

@router.delete("/{repo_id}/tracked", response_model=RepositoryResponse)
def untrack_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Stop syncing this repo. Its history and reports stay readable — sync passes
    just skip it. Idempotent."""
    return _named([repo_service.set_tracked(db, user, repo_id, False)])[0]

@router.put("/{repo_id}/lead/{user_id}", response_model=RepositoryResponse)
def set_lead(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Name the repo's lead — one of its two approvers. Must differ from the deputy."""
    return _named([repo_service.set_lead(db, user, repo_id, user_id)])[0]

@router.delete("/{repo_id}/lead", response_model=RepositoryResponse)
def clear_lead(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_lead(db, user, repo_id, None)])[0]

@router.put("/{repo_id}/deputy/{user_id}", response_model=RepositoryResponse)
def set_deputy(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Name the repo's deputy — the co-approver who covers the lead. Must differ."""
    return _named([repo_service.set_deputy(db, user, repo_id, user_id)])[0]

@router.delete("/{repo_id}/deputy", response_model=RepositoryResponse)
def clear_deputy(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return _named([repo_service.set_deputy(db, user, repo_id, None)])[0]

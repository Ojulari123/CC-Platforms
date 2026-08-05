from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.schemas.repositories import RepositoryResponse
from app.services import repositories as repo_service

router = APIRouter(prefix="/github/repositories", tags=["repositories"])

@router.get("", response_model=Page[RepositoryResponse])
def list_repositories(tracked_only: bool = Query(default=False), page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[RepositoryResponse]:
    repos = repo_service.list_repositories(db, tracked_only=tracked_only)
    window = repos[page.offset: page.offset + page.limit]
    return Page.of([RepositoryResponse.model_validate(r) for r in window], total=len(repos), params=page)

@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return repo_service.get_repository(db, repo_id)

@router.put("/{repo_id}/department/{dept_id}", response_model=RepositoryResponse)
def set_department(repo_id: int, dept_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return repo_service.set_department(db, user, repo_id, dept_id)

@router.put("/{repo_id}/lead/{user_id}", response_model=RepositoryResponse)
def set_lead(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Name the repo's lead — one of its two approvers. Must differ from the deputy."""
    return repo_service.set_lead(db, user, repo_id, user_id)

@router.delete("/{repo_id}/lead", response_model=RepositoryResponse)
def clear_lead(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return repo_service.set_lead(db, user, repo_id, None)

@router.put("/{repo_id}/deputy/{user_id}", response_model=RepositoryResponse)
def set_deputy(repo_id: int, user_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    """Name the repo's deputy — the co-approver who covers the lead. Must differ."""
    return repo_service.set_deputy(db, user, repo_id, user_id)

@router.delete("/{repo_id}/deputy", response_model=RepositoryResponse)
def clear_deputy(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return repo_service.set_deputy(db, user, repo_id, None)

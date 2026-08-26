from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.celery_app import BrokerUnavailableError
from app.db import get_db
from app.rate_limit import limiter, user_or_address_key
from app.schemas.repo_index import GitHubIndexStatus, IndexedRepoResponse, IndexRequest
from app.services import repo_index as repo_index_service
from app.services.llm_budget import BudgetExceededError

router = APIRouter(prefix="/chat/repos", tags=["repo-index"])

@router.get("", response_model=Page[IndexedRepoResponse])
def list_indexed_repos(page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[IndexedRepoResponse]:
    rows, total = repo_index_service.list_indexed_repos(db, user, limit=page.limit, offset=page.offset)
    return Page.of([IndexedRepoResponse.model_validate(r) for r in rows], total=total, params=page)

@router.post("", response_model=IndexedRepoResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour", key_func=user_or_address_key)
def index_public_repo(request: Request, payload: IndexRequest, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> IndexedRepoResponse:
    try:
        row = repo_index_service.queue_index(db, repo_index_service.request_public_index(db, user, payload.full_name))
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except BrokerUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return IndexedRepoResponse.model_validate(row)

# Declared before /{indexed_repo_id}: a literal segment has to be matched first, or
# "mine" and "github-status" are read as ids.
@router.post("/mine", response_model=list[IndexedRepoResponse], status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour", key_func=user_or_address_key)
def index_my_repos(request: Request, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> list[IndexedRepoResponse]:
    try:
        rows = repo_index_service.queue_indexes(db, repo_index_service.request_own_repos(db, user))
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except BrokerUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return [IndexedRepoResponse.model_validate(r) for r in rows]

@router.get("/github-status", response_model=GitHubIndexStatus)
def github_status(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> GitHubIndexStatus:
    return GitHubIndexStatus(**repo_index_service.github_status(db, user))

@router.get("/{indexed_repo_id}", response_model=IndexedRepoResponse)
def get_indexed_repo(indexed_repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> IndexedRepoResponse:
    return IndexedRepoResponse.model_validate(repo_index_service.get_indexed_repo(db, user, indexed_repo_id))

@router.delete("/{indexed_repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_indexed_repo(indexed_repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    repo_index_service.delete_indexed_repo(db, user, indexed_repo_id)

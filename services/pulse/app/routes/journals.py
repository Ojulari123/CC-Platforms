from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.services.provider_limits import ProviderRateLimited
from app.rate_limit import limiter, user_or_address_key
from app.schemas.journals import (
    JournalCreate, JournalResponse, JournalUpdate, LatestRollupResponse,
    RollupRequest, RollupResponse,
)
from app.services import journals as journals_service, people
from app.services.ai_provider import AIError
from app.services.journals import NoJournalEntriesError
from app.services.llm_budget import BudgetExceededError

router = APIRouter(prefix="/github/repositories/{repo_id}/journals", tags=["journals"])

def _named(rows) -> list[JournalResponse]:
    items = [JournalResponse.model_validate(r) for r in rows]
    people.attach_names(items, ("author_user_id", "author"))
    return items

def _named_rollup(rollup) -> RollupResponse:
    items = [RollupResponse.model_validate(rollup)]
    people.attach_names(items, ("generated_by_user_id", "generated_by"))
    return items[0]

@router.get("", response_model=Page[JournalResponse])
def list_journals(repo_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[JournalResponse]:
    items, total = journals_service.list_journals(db, user, repo_id, limit=page.limit, offset=page.offset)
    return Page.of(_named(items), total=total, params=page)

@router.post("", response_model=JournalResponse, status_code=status.HTTP_201_CREATED)
def create_journal(repo_id: int, payload: JournalCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> JournalResponse:
    return _named([journals_service.create_journal(db, user, repo_id, payload.body)])[0]

# Declared before /{journal_id}: a literal segment has to be matched first, or "rollup"
# is read as an entry id.
@router.get("/rollup", response_model=LatestRollupResponse)
def latest_rollup(repo_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> LatestRollupResponse:
    """200 with `rollup: null` when there is not one yet. A repository the caller cannot
    see is still a 404, so "nothing here" and "not yours" stay tellable apart, and a
    normal empty state stops arriving as an error in the browser console."""
    rollup = journals_service.latest_rollup(db, user, repo_id)
    return LatestRollupResponse(rollup=_named_rollup(rollup) if rollup is not None else None)

@router.post("/rollup", response_model=RollupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour", key_func=user_or_address_key)
def generate_rollup(request: Request, repo_id: int, payload: RollupRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RollupResponse:
    try:
        return _named_rollup(journals_service.generate_rollup(db, user, repo_id, payload.persona_id if payload else None))
    except NoJournalEntriesError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except ProviderRateLimited as exc:
        # Busy, not broken. 503 with Retry-After is what tells a caller to come back
        # rather than that something went wrong.
        raise HTTPException(
            status_code=503,
            detail=f"The AI rollup is busy right now. Try again in about {max(1, round(exc.wait_seconds))} second(s).",
            headers={"Retry-After": str(max(1, round(exc.wait_seconds)))},
        )
    except AIError:
        # Not interpolated: an AIError carries the provider's own exception, which can
        # name request URLs, models and org ids. The provider module already logs it.
        raise HTTPException(status_code=502, detail="The AI rollup is unavailable right now. Please try again shortly.")

@router.patch("/{journal_id}", response_model=JournalResponse)
def update_journal(repo_id: int, journal_id: int, payload: JournalUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> JournalResponse:
    return _named([journals_service.update_journal(db, user, repo_id, journal_id, payload.body)])[0]

@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_journal(repo_id: int, journal_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    journals_service.delete_journal(db, user, repo_id, journal_id)

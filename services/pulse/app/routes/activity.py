from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.auth import current_user
from app.db import get_db
from app.schemas.activity import ActivityResponse
from app.services import activity as activity_service, people

router = APIRouter(prefix="/activity", tags=["activity"])

def _named(response: ActivityResponse) -> ActivityResponse:
    people.attach_names([response], ("user_id", "user"))
    return response

@router.get("/me", response_model=ActivityResponse)
def my_activity(since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    return _named(activity_service.get_activity_response(db, user.user_id, since=since, repo_id=repo_id))

@router.get("/{user_id}", response_model=ActivityResponse)
def user_activity(user_id: int, since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    """A caller who oversees none of this person's repos gets an empty, zeroed response
    rather than a 403: reach is derived from which department each *repo* is filed under,
    so a 403 would fire just as loudly for a new joiner with no synced activity as for a
    real permissions problem. The empty answer also says nothing about who or what
    exists."""
    scope = activity_service.visible_repo_ids(db, user, user_id)
    return _named(activity_service.get_activity_response(db, user_id, since=since, repo_id=repo_id, repo_ids=scope))

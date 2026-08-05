from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.auth import current_user
from app.db import get_db
from app.schemas.activity import ActivityResponse
from app.services import activity as activity_service

router = APIRouter(prefix="/activity", tags=["activity"])

@router.get("/me", response_model=ActivityResponse)
def my_activity(since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    return activity_service.get_activity_response(db, user.user_id, since=since, repo_id=repo_id)

@router.get("/{user_id}", response_model=ActivityResponse)
def user_activity(user_id: int, since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    """An engineer's synced activity — counts + recent items. You can see your own;
    admins and repo leads/deputies can see others'."""
    if not activity_service.can_view(db, user, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't view this person's activity")
    return activity_service.get_activity_response(db, user_id, since=since, repo_id=repo_id)

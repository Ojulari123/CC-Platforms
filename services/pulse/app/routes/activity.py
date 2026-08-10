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
    """Fill the UserRef in one identity call. The person the response is about is the
    only user id on it — the recent commits/PRs/reviews/issues carry none — so this is
    one round trip per request. Names are decoration; unresolvable ids stay null."""
    people.attach_names([response], ("user_id", "user"))
    return response

@router.get("/me", response_model=ActivityResponse)
def my_activity(since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    return _named(activity_service.get_activity_response(db, user.user_id, since=since, repo_id=repo_id))

@router.get("/{user_id}", response_model=ActivityResponse)
def user_activity(user_id: int, since: date | None = Query(default=None), repo_id: int | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ActivityResponse:
    """An engineer's synced activity — counts + recent items. You can see your own;
    a platform admin sees anyone; a repo lead/deputy or a department admin sees only
    what this person did in the repos they oversee.

    Anyone with a token may ask, and gets back exactly what they are entitled to see —
    which for a caller who oversees none of this person's repos is an empty, zeroed
    response, not a 403. Pulse derives a manager's reach from which department each
    *repo* is filed under (it can't see identity's user→department data), so a 403
    here would fire just as loudly for a new joiner with no synced activity as for a
    genuine permissions problem. An empty response leaks nothing: it does not say
    whether the person exists, whether the repo filter names a real repo, or whether
    there was any activity to hide."""
    scope = activity_service.visible_repo_ids(db, user, user_id)
    return _named(activity_service.get_activity_response(db, user_id, since=since, repo_id=repo_id, repo_ids=scope))

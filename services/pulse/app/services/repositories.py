"""
Pulse owns this; people are referenced by identity `user_id`. 
Pulse can't see identity's role table, so it does NOT verify that an
assigned lead/deputy actually holds manager/admin — the assigning admin is
trusted for that (a future check could call identity's API). 

Pulse only enforces a platform admin, or an admin of the repo's department

Note: A repo's lead and deputy must be different people.
"""
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import Report, Repository

def _get_repo(db: Session, repo_id: int) -> Repository:
    repo = db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo

def _require_can_admin_repo(user: TokenClaims, repo: Repository) -> None:
    """Who may change a repo's lead/deputy: a platform admin, or an admin of the
    repo's current department. A repo with no department yet can only be
    administered by a platform admin (there's no dept admin to defer to)."""
    if user.is_platform_admin:
        return
    if repo.dept_id is not None and user.role_in(repo.dept_id) == "admin":
        return
    raise HTTPException(status_code=403, detail="Requires a platform admin or an admin of this repo's department")

def list_repositories(db: Session, tracked_only: bool = False) -> list[Repository]:
    q = select(Repository)
    if tracked_only:
        q = q.where(Repository.is_tracked.is_(True))
    return list(db.scalars(q.order_by(Repository.full_name)))

def get_repository(db: Session, repo_id: int) -> Repository:
    return _get_repo(db, repo_id)

def set_department(db: Session, user: TokenClaims, repo_id: int, dept_id: int) -> Repository:
    """File the repo under a department. An unfiled repo may be filed by an admin of
    the target department (no owner to take it from); an already-filed repo can only
    be moved by someone who admins BOTH its current and the target department, which
    stops a dept admin capturing another department's repo. A platform admin can put
    it anywhere.

    Reports carry a denormalised `dept_id`. Engineers open reports on a repo before it has a department,
    so those reports would be stranded with a null dept_id and stay invisible to the department admin. 
    
    Re-stamp every report on this repo so the snapshot follows the repo into (or between) departments."""
    repo = _get_repo(db, repo_id)
    if repo.dept_id is not None:
        _require_can_admin_repo(user, repo)
    if not user.is_platform_admin and user.role_in(dept_id) != "admin":
        raise HTTPException(status_code=403, detail="Requires a platform admin or an admin of that department")
    repo.dept_id = dept_id
    db.execute(update(Report).where(Report.repo_id == repo.id).values(dept_id=dept_id))
    db.commit()
    db.refresh(repo)
    return repo

def set_lead(db: Session, user: TokenClaims, repo_id: int, lead_user_id: int | None) -> Repository:
    repo = _get_repo(db, repo_id)
    _require_can_admin_repo(user, repo)
    if lead_user_id is not None and lead_user_id == repo.deputy_user_id:
        raise HTTPException(status_code=400, detail="The lead and deputy must be different people")
    repo.lead_user_id = lead_user_id
    db.commit()
    db.refresh(repo)
    return repo

def set_deputy(db: Session, user: TokenClaims, repo_id: int, deputy_user_id: int | None) -> Repository:
    repo = _get_repo(db, repo_id)
    _require_can_admin_repo(user, repo)
    if deputy_user_id is not None and deputy_user_id == repo.lead_user_id:
        raise HTTPException(status_code=400, detail="The lead and deputy must be different people")
    repo.deputy_user_id = deputy_user_id
    db.commit()
    db.refresh(repo)
    return repo

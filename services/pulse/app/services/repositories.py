"""
Pulse owns this; people are referenced by identity `user_id`. 
Pulse can't see identity's role table, so it does NOT verify that an
assigned lead/deputy actually holds manager/admin — the assigning admin is
trusted for that (a future check could call identity's API). 

Pulse only enforces a platform admin, or an admin of the repo's department

Note: A repo's lead and deputy must be different people.
"""
from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import Report, Repository
from app.services.activity import repo_ids_worked_in, repo_ids_worked_in_q

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

def _can_see_repo(db: Session, user: TokenClaims, repo: Repository) -> bool:
    """Who may see a repo exists at all: a platform admin, its lead or deputy, anyone
    in its department, or anyone who has actually worked in it. Same vocabulary as
    _require_can_admin_repo, one step looser — belonging to the department is enough
    to look, administering it is what you need to change anything.

    Worked-in matters because a freshly synced repo has no department yet: without it,
    syncing a repo would look like it did nothing until an admin filed it. "Worked in"
    is activity's definition (commit/PR/issue author, or PR reviewer), reused rather
    than restated."""
    if user.is_platform_admin:
        return True
    if user.user_id in (repo.lead_user_id, repo.deputy_user_id):
        return True
    if repo.dept_id is not None and user.is_member_of(repo.dept_id):
        return True
    return repo.id in repo_ids_worked_in(db, user.user_id)

def visible_repo_scope(user: TokenClaims) -> list:
    """_can_see_repo expressed as SQL, for any list that must be limited to repos the
    caller can see — change this and _can_see_repo together. Meaningless for a platform
    admin, who needs no filter; callers check that first."""
    scope = [
        Repository.lead_user_id == user.user_id,
        Repository.deputy_user_id == user.user_id,
        Repository.id.in_(repo_ids_worked_in_q(user.user_id)),
    ]
    if user.dept_ids:
        scope.append(Repository.dept_id.in_(user.dept_ids))
    return scope

def list_repositories(db: Session, user: TokenClaims, tracked_only: bool = False, limit: int = 50, offset: int = 0) -> tuple[list[Repository], int]:
    """Repos the caller can see, paged in SQL. Private repo names and the lead/deputy
    ids are not public within the company, so this filters rather than returning
    everything to every valid token."""
    q = select(Repository)
    if tracked_only:
        q = q.where(Repository.is_tracked.is_(True))
    if not user.is_platform_admin:
        q = q.where(or_(*visible_repo_scope(user)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Repository.full_name).limit(limit).offset(offset))
    return list(rows), total

def get_repository(db: Session, user: TokenClaims, repo_id: int) -> Repository:
    """404 (not 403) on a repo the caller can't see — a 403 would confirm that a
    private repo with that id exists."""
    repo = _get_repo(db, repo_id)
    if not _can_see_repo(db, user, repo):
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo

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

def set_tracked(db: Session, user: TokenClaims, repo_id: int, tracked: bool) -> Repository:
    """Turn syncing for a repo on or off. Same admin rule as lead/deputy — deciding
    whether a repo's activity is pulled at all is an admin call, not an engineer's.

    Untracking hides nothing: the repo, its history and its reports stay readable
    (see _can_see_repo). It only stops the next sync pass from spending API quota on
    it. Hiding it would strand existing reports and leave no way to turn it back on."""
    repo = _get_repo(db, repo_id)
    _require_can_admin_repo(user, repo)
    repo.is_tracked = tracked
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

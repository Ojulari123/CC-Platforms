"""Pulse can't see identity's role table, so it does NOT verify that an assigned
lead/deputy actually holds manager/admin — the assigning admin is trusted for that (a
future check could call identity's API).
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
    if user.is_platform_admin:
        return
    if repo.dept_id is not None and user.role_in(repo.dept_id) == "admin":
        return
    raise HTTPException(status_code=403, detail="Requires a platform admin or an admin of this repo's department")

def _can_file_repos(user: TokenClaims) -> bool:
    return user.is_platform_admin or any(m.role == "admin" for m in user.memberships)

def _can_see_repo(db: Session, user: TokenClaims, repo: Repository) -> bool:
    if user.is_platform_admin:
        return True
    if user.user_id in (repo.lead_user_id, repo.deputy_user_id):
        return True
    if repo.dept_id is not None and user.is_member_of(repo.dept_id):
        return True
    return repo.id in repo_ids_worked_in(db, user.user_id)

def visible_repo_scope(user: TokenClaims) -> list:
    """_can_see_repo expressed as SQL — change this and _can_see_repo together."""
    scope = [
        Repository.lead_user_id == user.user_id,
        Repository.deputy_user_id == user.user_id,
        Repository.id.in_(repo_ids_worked_in_q(user.user_id)),
    ]
    if user.dept_ids:
        scope.append(Repository.dept_id.in_(user.dept_ids))
    return scope

def list_repositories(db: Session, user: TokenClaims, tracked_only: bool = False, limit: int = 50, offset: int = 0) -> tuple[list[Repository], int]:
    q = select(Repository)
    if tracked_only:
        q = q.where(Repository.is_tracked.is_(True))
    if not user.is_platform_admin:
        q = q.where(or_(*visible_repo_scope(user)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Repository.full_name).limit(limit).offset(offset))
    return list(rows), total

def unfiled_repositories(db: Session, user: TokenClaims, limit: int = 50, offset: int = 0) -> tuple[list[Repository], int]:
    """Deliberately NOT filtered by visible_repo_scope: an unfiled repo is invisible to
    a dept admin who never committed to it, and that is precisely the person who should
    file it. Only admins reach this, and set_department already lets any dept admin file
    any unfiled repo by id — so this adds discovery, not power."""
    if not _can_file_repos(user):
        raise HTTPException(status_code=403, detail="Requires a platform admin or a department admin")
    q = select(Repository).where(Repository.dept_id.is_(None))
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

def _apply_department(db: Session, user: TokenClaims, repo: Repository, dept_id: int) -> None:
    if repo.dept_id is not None:
        _require_can_admin_repo(user, repo)
    if not user.is_platform_admin and user.role_in(dept_id) != "admin":
        raise HTTPException(status_code=403, detail="Requires a platform admin or an admin of that department")
    repo.dept_id = dept_id
    db.execute(update(Report).where(Report.repo_id == repo.id).values(dept_id=dept_id))

def set_department(db: Session, user: TokenClaims, repo_id: int, dept_id: int) -> Repository:
    """Reports carry a denormalised `dept_id`, and engineers open them before a repo is
    filed, so every report on the repo is re-stamped here — otherwise they stay stranded
    with a null dept_id, invisible to the department admin who should approve them."""
    repo = _get_repo(db, repo_id)
    _apply_department(db, user, repo, dept_id)
    db.commit()
    db.refresh(repo)
    return repo

def set_departments(db: Session, user: TokenClaims, repo_ids: list[int], dept_id: int) -> list[Repository]:
    repos = [_get_repo(db, rid) for rid in dict.fromkeys(repo_ids)]
    try:
        for repo in repos:
            _apply_department(db, user, repo, dept_id)
    except HTTPException:
        db.rollback()
        raise
    db.commit()
    for repo in repos:
        db.refresh(repo)
    return repos

def set_tracked(db: Session, user: TokenClaims, repo_id: int, tracked: bool) -> Repository:
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

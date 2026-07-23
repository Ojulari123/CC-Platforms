import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Department, Membership, Team, User
from app.schemas.departments import DepartmentUpdate, MemberListResponse, MemberResponse, MemberUpdate, TeamCreate, TeamUpdate

def get_department(db: Session, dept_id: int) -> Department:
    department = db.get(Department, dept_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return department

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "team"

def _unique_dept_slug(db: Session, base: str, exclude_id: int) -> str:
    slug = base
    n = 1
    while db.scalar(select(Department).where(Department.slug == slug, Department.id != exclude_id)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def _unique_team_slug(db: Session, dept_id: int, base: str, exclude_id: int | None = None) -> str:
    slug = base
    n = 1
    while db.scalar(select(Team).where(Team.dept_id == dept_id, Team.slug == slug, Team.id != exclude_id)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def update_department(db: Session, dept_id: int, payload: DepartmentUpdate) -> Department:
    """Rename the department. The slug follows the name — same rule as creation,
    so a renamed department doesn't keep a slug that contradicts it."""
    department = get_department(db, dept_id)
    department.name = payload.name
    department.slug = _unique_dept_slug(db, _slugify(payload.name), exclude_id=dept_id)
    db.commit()
    db.refresh(department)
    return department

def create_team(db: Session, dept_id: int, payload: TeamCreate) -> Team:
    team = Team(dept_id=dept_id, name=payload.name, slug=_unique_team_slug(db, dept_id, _slugify(payload.name)))
    db.add(team)
    db.commit()
    db.refresh(team)
    return team

def list_teams(db: Session, dept_id: int) -> list[Team]:
    return list(db.scalars(select(Team).where(Team.dept_id == dept_id).order_by(Team.name)))

def _get_team(db: Session, dept_id: int, team_id: int) -> Team:
    team = db.scalar(select(Team).where(Team.id == team_id, Team.dept_id == dept_id))
    if not team:
        raise HTTPException(status_code=404, detail="Team not found in this department")
    return team

def update_team(db: Session, dept_id: int, team_id: int, payload: TeamUpdate) -> Team:
    team = _get_team(db, dept_id, team_id)
    team.name = payload.name
    team.slug = _unique_team_slug(db, dept_id, _slugify(payload.name), exclude_id=team_id)
    db.commit()
    db.refresh(team)
    return team

def delete_team(db: Session, dept_id: int, team_id: int) -> None:
    """Delete a team. Members of it stay in the department — their team_id just
    goes null (the FK is ON DELETE SET NULL). Deleting a team must never
    silently delete people."""
    team = _get_team(db, dept_id, team_id)
    db.delete(team)
    db.commit()

def remove_member(db: Session, dept_id: int, member_user_id: int) -> None:
    """Remove someone from the department. Deletes the membership only — the
    user account itself survives, so they keep any other department they're in
    and can be re-invited. Their sessions are revoked so the removal takes
    effect immediately rather than at token expiry."""
    membership = db.scalar(select(Membership).where(Membership.user_id == member_user_id, Membership.dept_id == dept_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this department")

    if membership.role == "admin":
        other_admins = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.dept_id == dept_id, Membership.role == "admin",
                Membership.is_active.is_(True), Membership.user_id != member_user_id,
            )
        )
        if not other_admins:
            raise HTTPException(status_code=400, detail="Cannot remove the only admin of the department")

    db.delete(membership)
    db.commit()
    # Kill their tokens *after* the membership is gone, so the bumped
    # token_version is what any in-flight request sees.
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, member_user_id)

def list_members(db: Session, dept_id: int, limit: int, offset: int) -> MemberListResponse:
    base = select(Membership).where(Membership.dept_id == dept_id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.dept_id == dept_id)
        .order_by(User.first_name, User.last_name)
        .limit(limit).offset(offset)
    ).all()
    items = [
        MemberResponse(
            user_id=u.id, email=u.email, first_name=u.first_name, last_name=u.last_name,
            role=m.role, team_id=m.team_id, is_active=m.is_active,
        )
        for m, u in rows
    ]
    return MemberListResponse(items=items, total=total or 0, limit=limit, offset=offset)

def update_member(db: Session, dept_id: int, member_user_id: int, payload: MemberUpdate) -> MemberResponse:
    membership = db.scalar(select(Membership).where(Membership.user_id == member_user_id, Membership.dept_id == dept_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this department")

    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] != "admin" and membership.role == "admin":
        # Last-admin guard: a department must always keep at least one admin.
        other_admins = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.dept_id == dept_id, Membership.role == "admin",
                Membership.is_active.is_(True), Membership.user_id != member_user_id,
            )
        )
        if not other_admins:
            raise HTTPException(status_code=400, detail="Cannot demote the only admin of the department")
    if "team_id" in changes and changes["team_id"] is not None:
        team = db.scalar(select(Team).where(Team.id == changes["team_id"], Team.dept_id == dept_id))
        if not team:
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

    for field, value in changes.items():
        setattr(membership, field, value)
    db.commit()
    db.refresh(membership)

    user = db.get(User, member_user_id)
    return MemberResponse(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, team_id=membership.team_id, is_active=membership.is_active,
    )

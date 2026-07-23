"""Departments and their member roster. Teams live in services/teams.py."""
import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Department, Membership, Team, User
from app.schemas.departments import DepartmentCreate, DepartmentUpdate, MemberListResponse, MemberResponse, MemberUpdate

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "department"

def _unique_dept_slug(db: Session, base: str, exclude_id: int | None = None) -> str:
    slug = base
    n = 1
    while db.scalar(select(Department).where(Department.slug == slug, Department.id != exclude_id)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def get_department(db: Session, dept_id: int) -> Department:
    department = db.get(Department, dept_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return department

def list_departments(db: Session) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.name)))

def create_department(db: Session, payload: DepartmentCreate) -> Department:
    department = Department(name=payload.name, slug=_unique_dept_slug(db, _slugify(payload.name)))
    db.add(department)
    db.commit()
    db.refresh(department)
    return department

def update_department(db: Session, dept_id: int, payload: DepartmentUpdate) -> Department:
    """Rename the department. The slug follows the name — same rule as creation,
    so a renamed department doesn't keep a slug that contradicts it."""
    department = get_department(db, dept_id)
    department.name = payload.name
    department.slug = _unique_dept_slug(db, _slugify(payload.name), exclude_id=dept_id)
    db.commit()
    db.refresh(department)
    return department

def delete_department(db: Session, dept_id: int) -> None:
    """Only an empty department can go. Deleting one with people in it would
    cascade their memberships away and silently strip their access."""
    department = get_department(db, dept_id)
    members = db.scalar(select(func.count()).select_from(Membership).where(Membership.dept_id == dept_id))
    if members:
        raise HTTPException(status_code=400, detail=f"Department still has {members} member(s) — remove them first")
    db.delete(department)
    db.commit()

def list_members(db: Session, dept_id: int, limit: int, offset: int) -> MemberListResponse:
    total = db.scalar(select(func.count()).select_from(Membership).where(Membership.dept_id == dept_id))
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

def _get_membership(db: Session, dept_id: int, member_user_id: int) -> Membership:
    membership = db.scalar(select(Membership).where(Membership.user_id == member_user_id, Membership.dept_id == dept_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this department")
    return membership

def _assert_not_last_admin(db: Session, dept_id: int, member_user_id: int, action: str) -> None:
    other_admins = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.dept_id == dept_id, Membership.role == "admin",
            Membership.is_active.is_(True), Membership.user_id != member_user_id,
        )
    )
    if not other_admins:
        raise HTTPException(status_code=400, detail=f"Cannot {action} the only admin of the department")

def _to_member_response(db: Session, membership: Membership) -> MemberResponse:
    user = db.get(User, membership.user_id)
    return MemberResponse(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, team_id=membership.team_id, is_active=membership.is_active,
    )

def update_member(db: Session, dept_id: int, member_user_id: int, payload: MemberUpdate) -> MemberResponse:
    membership = _get_membership(db, dept_id, member_user_id)

    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] != "admin" and membership.role == "admin":
        _assert_not_last_admin(db, dept_id, member_user_id, "demote")
    if "team_id" in changes and changes["team_id"] is not None:
        if not db.scalar(select(Team).where(Team.id == changes["team_id"], Team.dept_id == dept_id)):
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

    for field, value in changes.items():
        setattr(membership, field, value)
    db.commit()
    db.refresh(membership)
    return _to_member_response(db, membership)

def remove_member(db: Session, dept_id: int, member_user_id: int) -> None:
    """Remove someone from the department. Deletes the membership only — the
    user account survives, so they keep any other department they're in and can
    be re-invited. Their sessions are revoked so the removal takes effect
    immediately rather than at token expiry."""
    membership = _get_membership(db, dept_id, member_user_id)
    if membership.role == "admin":
        _assert_not_last_admin(db, dept_id, member_user_id, "remove")

    # Vacate any team they lead here, so no team is left pointing at someone
    # who is no longer in the department.
    db.query(Team).filter(Team.dept_id == dept_id, Team.manager_user_id == member_user_id).update(
        {"manager_user_id": None}, synchronize_session=False
    )
    db.delete(membership)
    db.commit()
    # Bump tokens *after* the membership is gone so re-issued claims are correct.
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, member_user_id)

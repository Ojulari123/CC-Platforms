import re
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Department, Membership, Team, User
from app.schemas.departments import DepartmentCreate, DepartmentResponse, DepartmentUpdate, MemberListResponse, MemberResponse, MemberUpdate

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

def _to_dept_response(db: Session, department: Department) -> DepartmentResponse:
    head = db.get(User, department.head_user_id) if department.head_user_id else None
    return DepartmentResponse(
        id=department.id, name=department.name, slug=department.slug,
        head_user_id=department.head_user_id,
        head_name=f"{head.first_name} {head.last_name}" if head else None,
    )

def get_department_response(db: Session, dept_id: int) -> DepartmentResponse:
    return _to_dept_response(db, get_department(db, dept_id))

def list_departments(db: Session) -> list[DepartmentResponse]:
    return [_to_dept_response(db, d) for d in db.scalars(select(Department).order_by(Department.name))]

def set_head(db: Session, dept_id: int, head_user_id: int | None) -> DepartmentResponse:
    """Name (or clear) the head. They must already be an admin here — granting that
    silently would hide a privilege change inside a title change. Promote first."""
    department = get_department(db, dept_id)

    if head_user_id is not None:
        membership = db.scalar(select(Membership).where(
            Membership.user_id == head_user_id,
            Membership.dept_id == dept_id,
        ))
        if not membership:
            raise HTTPException(status_code=400, detail="The head must be a member of this department")
        if membership.role != "admin":
            raise HTTPException(status_code=400, detail="The head must have the admin role — promote them first")

    department.head_user_id = head_user_id
    db.commit()
    db.refresh(department)
    return _to_dept_response(db, department)

def create_department(db: Session, payload: DepartmentCreate) -> DepartmentResponse:
    department = Department(name=payload.name, slug=_unique_dept_slug(db, _slugify(payload.name)))
    db.add(department)
    db.commit()
    db.refresh(department)
    return _to_dept_response(db, department)

def update_department(db: Session, dept_id: int, payload: DepartmentUpdate) -> DepartmentResponse:
    department = get_department(db, dept_id)
    department.name = payload.name
    department.slug = _unique_dept_slug(db, _slugify(payload.name), exclude_id=dept_id)
    db.commit()
    db.refresh(department)
    return _to_dept_response(db, department)

def delete_department(db: Session, dept_id: int) -> None:
    """Only an empty department can go. Deleting one with people in it would
    cascade their memberships away and silently strip their access."""
    department = get_department(db, dept_id)
    members = db.scalar(select(func.count()).select_from(Membership).where(Membership.dept_id == dept_id))
    if members:
        raise HTTPException(status_code=400, detail=f"Department still has {members} member(s) — remove them first")
    db.delete(department)
    db.commit()

def list_members(db: Session, dept_id: int, limit: int, offset: int, role: str | None = None, team_id: int | None = None, q: str | None = None) -> MemberListResponse:
    # Without this an unknown department answers 200 with an empty page, which
    # reads as "nobody works here" rather than "no such department" — and
    # GET /departments/{dept_id} already 404s.
    if not db.get(Department, dept_id):
        raise HTTPException(status_code=404, detail="Department not found")

    base = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.dept_id == dept_id)
    )
    if role is not None:
        base = base.where(Membership.role == role)
    if team_id is not None:
        base = base.where(Membership.team_id == team_id)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(
            func.lower(User.first_name).like(like),
            func.lower(User.last_name).like(like),
            func.lower(User.email).like(like),
        ))

    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(User.first_name, User.last_name).limit(limit).offset(offset)
    ).all()
    items = [
        MemberResponse(
            user_id=u.id, email=u.email, first_name=u.first_name, last_name=u.last_name,
            role=m.role, team_id=m.team_id, is_active=u.is_active,
        )
        for m, u in rows
    ]
    return MemberListResponse(items=items, total=total or 0, limit=limit, offset=offset)

def add_member(db: Session, dept_id: int, user_id: int, role: str, team_id: int | None = None) -> MemberResponse:
    if not db.get(Department, dept_id):
        raise HTTPException(status_code=404, detail="Department not found")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.dept_id == dept_id)):
        raise HTTPException(status_code=409, detail="That person is already a member of this department")

    if team_id is not None:
        if not db.scalar(select(Team).where(Team.id == team_id, Team.dept_id == dept_id)):
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

    membership = Membership(user_id=user_id, dept_id=dept_id, team_id=team_id, role=role)
    db.add(membership)
    if user.onboarded_at is None:
        user.onboarded_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That person is already a member of this department")
    db.refresh(membership)
    return _to_member_response(db, membership)

def _get_membership(db: Session, dept_id: int, member_user_id: int) -> Membership:
    membership = db.scalar(select(Membership).where(Membership.user_id == member_user_id, Membership.dept_id == dept_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this department")
    return membership

def _assert_not_last_admin(db: Session, dept_id: int, member_user_id: int, action: str) -> None:
    other_admins = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.dept_id == dept_id, Membership.role == "admin",
            Membership.user_id != member_user_id,
        )
    )
    if not other_admins:
        raise HTTPException(status_code=400, detail=f"Cannot {action} the only admin of the department")

def _to_member_response(db: Session, membership: Membership) -> MemberResponse:
    user = db.get(User, membership.user_id)
    return MemberResponse(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, team_id=membership.team_id, is_active=user.is_active,
    )

def update_member(db: Session, dept_id: int, member_user_id: int, payload: MemberUpdate, replacement_user_id: int | None = None, allow_unled: bool = False) -> MemberResponse:
    membership = _get_membership(db, dept_id, member_user_id)

    changes = payload.model_dump(exclude_unset=True)
    new_role = changes.get("role")
    if new_role is not None and new_role != membership.role:
        if membership.role == "admin" and new_role != "admin":
            _assert_not_last_admin(db, dept_id, member_user_id, "demote")
        _handover(
            db, dept_id, member_user_id, replacement_user_id, allow_unled,
            # Leading a team needs manager-or-admin; heading a department needs admin.
            losing_team_leadership=new_role not in ("manager", "admin"),
            losing_headship=new_role != "admin",
            action=f"Demoting them to {new_role}",
        )

    if "team_id" in changes and changes["team_id"] is not None:
        if not db.scalar(select(Team).where(Team.id == changes["team_id"], Team.dept_id == dept_id)):
            raise HTTPException(status_code=400, detail="Team does not belong to this department")

    for field, value in changes.items():
        setattr(membership, field, value)
    db.commit()
    db.refresh(membership)
    return _to_member_response(db, membership)

def _handover(db: Session, dept_id: int, user_id: int, replacement_user_id: int | None, allow_unled: bool, *, losing_team_leadership: bool = True, losing_headship: bool = True, action: str = "Removing them") -> None:
    """Deal with whatever this person is in charge of before they stop being able
    to do it"""
    department = get_department(db, dept_id)
    led_teams = (
        list(db.scalars(select(Team).where(Team.dept_id == dept_id, Team.manager_user_id == user_id)))
        if losing_team_leadership else []
    )
    heads_dept = losing_headship and department.head_user_id == user_id
    if not led_teams and not heads_dept:
        return

    if replacement_user_id is not None:
        if replacement_user_id == user_id:
            raise HTTPException(status_code=400, detail="The replacement cannot be the same person")
        replacement = db.scalar(select(Membership).where(
            Membership.user_id == replacement_user_id,
            Membership.dept_id == dept_id,
        ))
        if not replacement:
            raise HTTPException(status_code=400, detail="The replacement must be a member of this department")
        if replacement.role not in ("manager", "admin"):
            raise HTTPException(status_code=400, detail="The replacement must have the manager or admin role")
        if heads_dept and replacement.role != "admin":
            raise HTTPException(status_code=400, detail="The replacement must have the admin role to head the department")
        for team in led_teams:
            team.manager_user_id = replacement_user_id
        if heads_dept:
            department.head_user_id = replacement_user_id
        return

    if allow_unled:
        for team in led_teams:
            team.manager_user_id = None
        if heads_dept:
            department.head_user_id = None
        return

    what = [f"leads {t.name}" for t in led_teams]
    if heads_dept:
        what.append(f"heads {department.name}")
    raise HTTPException(
        status_code=409,
        detail=(
            f"That person {' and '.join(what)}. {action} leaves that without anyone in charge. "
            "Pass replacement_user_id to hand it over, or allow_unled=true to proceed anyway."
        ),
    )

def remove_member(db: Session, dept_id: int, member_user_id: int, replacement_user_id: int | None = None, allow_unled: bool = False) -> None:
    """Deletes the membership only — the account survives, keeping any other
    department. Sessions are revoked so it takes effect now, not at token expiry."""
    membership = _get_membership(db, dept_id, member_user_id)
    if membership.role == "admin":
        _assert_not_last_admin(db, dept_id, member_user_id, "remove")

    _handover(db, dept_id, member_user_id, replacement_user_id, allow_unled)
    db.delete(membership)
    db.commit()
    # Bump tokens *after* the membership is gone so re-issued claims are correct.
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, member_user_id)

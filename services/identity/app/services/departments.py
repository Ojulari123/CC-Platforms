"""Departments and their member roster. Teams live in services/teams.py."""
import re
from fastapi import HTTPException
from sqlalchemy import func, select
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
    """Name (or clear) the head of the department — the person who runs it, as
    opposed to everyone who happens to hold the admin role.

    They must be a member with role=admin: the head needs to be able to do
    everything in the department, and silently granting that here would hide a
    privilege change inside what looks like a title change. Promote them first
    if needed. Like a team lead, this is a title, not a team assignment."""
    department = get_department(db, dept_id)

    if head_user_id is not None:
        membership = db.scalar(select(Membership).where(
            Membership.user_id == head_user_id,
            Membership.dept_id == dept_id,
            Membership.is_active.is_(True),
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
    """Rename the department. The slug follows the name — same rule as creation,
    so a renamed department doesn't keep a slug that contradicts it."""
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

def update_member(
    db: Session,
    dept_id: int,
    member_user_id: int,
    payload: MemberUpdate,
    replacement_user_id: int | None = None,
    allow_unled: bool = False,
) -> MemberResponse:
    """Change someone's role or team.

    A role is only validated when a title is *granted* — so without the handover
    check below, demoting a team lead to engineer left them still leading the
    team AND still able to manage its roster, because permission is read from
    Team.manager_user_id and never re-checks the role. Demotion is exactly when
    access is expected to stop, so a role change now has to resolve any title it
    invalidates."""
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

def _handover(
    db: Session,
    dept_id: int,
    user_id: int,
    replacement_user_id: int | None,
    allow_unled: bool,
    *,
    losing_team_leadership: bool = True,
    losing_headship: bool = True,
    action: str = "Removing them",
) -> None:
    """Deal with whatever this person is in charge of before they stop being able
    to do it — whether that's because they're leaving the department, or because
    they've been demoted out of the role the title requires.

    Refuses rather than silently creating a gap: a team with no lead has nobody
    to approve its weekly reports, and that's the kind of thing you only notice
    weeks later. The caller either names a successor or says they accept it.

    The two `losing_*` flags exist because a demotion doesn't always invalidate
    both titles — manager→admin keeps you eligible to lead teams, while
    admin→manager still costs you the headship."""
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
            Membership.is_active.is_(True),
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
    """Remove someone from the department. Deletes the membership only — the
    user account survives, so they keep any other department they're in and can
    be re-invited. Their sessions are revoked so the removal takes effect
    immediately rather than at token expiry."""
    membership = _get_membership(db, dept_id, member_user_id)
    if membership.role == "admin":
        _assert_not_last_admin(db, dept_id, member_user_id, "remove")

    _handover(db, dept_id, member_user_id, replacement_user_id, allow_unled)
    db.delete(membership)
    db.commit()
    # Bump tokens *after* the membership is gone so re-issued claims are correct.
    from app.services.auth import revoke_all_for_user
    revoke_all_for_user(db, member_user_id)

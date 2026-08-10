"""Teams sit inside a department; a person's team is on their membership. One team
per person, so a Pulse report has exactly one approving manager — splitting across
teams means a join table (docs/decisions/2026-07-23-identity-structure.md)."""
import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased
from app.models import Department, Membership, Team, User
from app.schemas.departments import MemberResponse, TeamCreate, TeamListItem, TeamResponse, TeamUpdate

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "team"

def _unique_team_slug(db: Session, dept_id: int, base: str, exclude_id: int | None = None) -> str:
    slug = base
    n = 1
    while db.scalar(select(Team).where(Team.dept_id == dept_id, Team.slug == slug, Team.id != exclude_id)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def get_team(db: Session, dept_id: int, team_id: int) -> Team:
    team = db.scalar(select(Team).where(Team.id == team_id, Team.dept_id == dept_id))
    if not team:
        raise HTTPException(status_code=404, detail="Team not found in this department")
    return team

def list_teams(db: Session, dept_id: int) -> list[TeamResponse]:
    teams = db.scalars(select(Team).where(Team.dept_id == dept_id).order_by(Team.name))
    return [_to_team_response(db, t) for t in teams]

def list_all_teams(db: Session, user: User) -> list[TeamListItem]:
    """Every team the caller is allowed to see, across departments — a platform
    admin sees the whole company; anyone else sees the departments they're in.
    Saves hunting for a dept_id just to look around."""
    member_count = (
        select(Membership.team_id, func.count().label("n"))
        .where(Membership.team_id.is_not(None))
        .group_by(Membership.team_id)
        .subquery()
    )
    lead = aliased(User)
    q = (
        select(Team, Department.name, func.coalesce(member_count.c.n, 0), lead)
        .join(Department, Department.id == Team.dept_id)
        .outerjoin(member_count, member_count.c.team_id == Team.id)
        .outerjoin(lead, lead.id == Team.manager_user_id)
    )
    if not user.is_platform_admin:
        mine = select(Membership.dept_id).where(Membership.user_id == user.id)
        q = q.where(Team.dept_id.in_(mine))
    rows = db.execute(q.order_by(Department.name, Team.name)).all()
    return [
        TeamListItem(
            id=t.id, name=t.name, slug=t.slug,
            dept_id=t.dept_id, dept_name=dept_name, member_count=count,
            manager_user_id=t.manager_user_id,
            manager_name=f"{lead_user.first_name} {lead_user.last_name}" if lead_user else None,
        )
        for t, dept_name, count, lead_user in rows
    ]

def create_team(db: Session, dept_id: int, payload: TeamCreate) -> Team:
    # A platform admin passes the dept_id guard without a membership lookup, so
    # nothing upstream has proved the department exists.
    if not db.get(Department, dept_id):
        raise HTTPException(status_code=404, detail="Department not found")

    team = Team(dept_id=dept_id, name=payload.name, slug=_unique_team_slug(db, dept_id, _slugify(payload.name)))
    db.add(team)
    db.commit()
    db.refresh(team)
    return team

def _to_team_response(db: Session, team: Team) -> TeamResponse:
    lead = db.get(User, team.manager_user_id) if team.manager_user_id else None
    return TeamResponse(
        id=team.id, dept_id=team.dept_id, name=team.name, slug=team.slug,
        manager_user_id=team.manager_user_id,
        manager_name=f"{lead.first_name} {lead.last_name}" if lead else None,
    )

def set_manager(db: Session, dept_id: int, team_id: int, manager_user_id: int | None) -> TeamResponse:
    """Appoint (or clear) the team's lead. Must already hold manager or admin —
    otherwise an engineer ends up approving their peers' reports by accident.
    Leading and being rostered are separate, so this moves and vacates nothing."""
    team = get_team(db, dept_id, team_id)

    if manager_user_id is not None:
        membership = db.scalar(select(Membership).where(
            Membership.user_id == manager_user_id,
            Membership.dept_id == dept_id,
        ))
        if not membership:
            raise HTTPException(status_code=400, detail="The team lead must be a member of this department")
        if membership.role not in ("manager", "admin"):
            raise HTTPException(status_code=400, detail="The team lead must have the manager or admin role")

    team.manager_user_id = manager_user_id
    db.commit()
    db.refresh(team)
    return _to_team_response(db, team)

def update_team(db: Session, dept_id: int, team_id: int, payload: TeamUpdate) -> TeamResponse:
    """Rename only. The lead has its own endpoint — a privilege change doesn't belong
    hidden inside a rename."""
    team = get_team(db, dept_id, team_id)
    team.name = payload.name
    team.slug = _unique_team_slug(db, dept_id, _slugify(payload.name), exclude_id=team_id)
    db.commit()
    db.refresh(team)
    return _to_team_response(db, team)

def delete_team(db: Session, dept_id: int, team_id: int) -> None:
    """Delete a team. Its people stay in the department — their team_id just goes
    null (the FK is ON DELETE SET NULL). Deleting a team must never quietly
    delete people."""
    team = get_team(db, dept_id, team_id)
    db.delete(team)
    db.commit()

def list_team_members(db: Session, dept_id: int, team_id: int) -> list[MemberResponse]:
    get_team(db, dept_id, team_id)  # 404s if the team isn't in this department
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.dept_id == dept_id, Membership.team_id == team_id)
        .order_by(User.first_name, User.last_name)
    ).all()
    return [
        MemberResponse(
            user_id=u.id, email=u.email, first_name=u.first_name, last_name=u.last_name,
            role=m.role, team_id=m.team_id, is_active=u.is_active,
        )
        for m, u in rows
    ]

def _membership_in_dept(db: Session, dept_id: int, user_id: int) -> Membership:
    membership = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.dept_id == dept_id))
    if not membership:
        raise HTTPException(status_code=404, detail="That person is not a member of this department")
    return membership

def add_team_member(db: Session, dept_id: int, team_id: int, user_id: int) -> MemberResponse:
    """Put someone on the team. They must already be in the department — teams
    are a subdivision of a department, not a separate way in. Idempotent:
    re-adding someone already on the team is a no-op rather than an error."""
    get_team(db, dept_id, team_id)
    membership = _membership_in_dept(db, dept_id, user_id)
    membership.team_id = team_id
    db.commit()
    db.refresh(membership)
    user = db.get(User, user_id)
    return MemberResponse(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, team_id=membership.team_id, is_active=user.is_active,
    )

def remove_team_member(db: Session, dept_id: int, team_id: int, user_id: int) -> None:
    """Off the roster, still in the department — and still leading it if they did.
    Use DELETE .../manager to step someone down."""
    get_team(db, dept_id, team_id)
    membership = _membership_in_dept(db, dept_id, user_id)
    if membership.team_id != team_id:
        raise HTTPException(status_code=404, detail="That person is not on this team")
    membership.team_id = None
    db.commit()

def get_team_response(db: Session, dept_id: int, team_id: int) -> TeamResponse:
    """get_team returns the ORM row (callers that need the object); this returns
    the API shape, which carries the lead's name."""
    return _to_team_response(db, get_team(db, dept_id, team_id))

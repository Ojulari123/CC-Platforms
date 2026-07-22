import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Membership, Team, User
from app.schemas.orgs import MemberListResponse, MemberResponse, MemberUpdate, TeamCreate

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "team"

def _unique_team_slug(db: Session, org_id: int, base: str) -> str:
    slug = base
    n = 1
    while db.scalar(select(Team).where(Team.org_id == org_id, Team.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug

def create_team(db: Session, org_id: int, payload: TeamCreate) -> Team:
    team = Team(org_id=org_id, name=payload.name, slug=_unique_team_slug(db, org_id, _slugify(payload.name)))
    db.add(team)
    db.commit()
    db.refresh(team)
    return team

def list_teams(db: Session, org_id: int) -> list[Team]:
    return list(db.scalars(select(Team).where(Team.org_id == org_id).order_by(Team.name)))

def list_members(db: Session, org_id: int, limit: int, offset: int) -> MemberListResponse:
    base = select(Membership).where(Membership.org_id == org_id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
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

def update_member(db: Session, org_id: int, member_user_id: int, payload: MemberUpdate) -> MemberResponse:
    membership = db.scalar(select(Membership).where(Membership.user_id == member_user_id, Membership.org_id == org_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this organisation")

    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] != "admin" and membership.role == "admin":
        # Last-admin guard: an org must always keep at least one admin.
        other_admins = db.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.org_id == org_id, Membership.role == "admin",
                Membership.is_active.is_(True), Membership.user_id != member_user_id,
            )
        )
        if not other_admins:
            raise HTTPException(status_code=400, detail="Cannot demote the only admin of the organisation")
    if "team_id" in changes and changes["team_id"] is not None:
        team = db.scalar(select(Team).where(Team.id == changes["team_id"], Team.org_id == org_id))
        if not team:
            raise HTTPException(status_code=400, detail="Team does not belong to this organisation")

    for field, value in changes.items():
        setattr(membership, field, value)
    db.commit()
    db.refresh(membership)

    user = db.get(User, member_user_id)
    return MemberResponse(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, team_id=membership.team_id, is_active=membership.is_active,
    )

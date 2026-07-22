from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.orgs import InviteCreate, InviteResponse, MemberListResponse, MemberResponse, MemberUpdate, TeamCreate, TeamResponse
from app.security import get_current_user, require_org_role
from app.services import invites as invites_service
from app.services import orgs as orgs_service

router = APIRouter(prefix="/orgs", tags=["orgs"])

@router.post("/{org_id}/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(org_id: int, payload: TeamCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamResponse:
    require_org_role(db, user, org_id, "admin")
    return orgs_service.create_team(db, org_id, payload)

@router.get("/{org_id}/teams", response_model=list[TeamResponse])
def list_teams(org_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TeamResponse]:
    require_org_role(db, user, org_id)  # any member
    return orgs_service.list_teams(db, org_id)

@router.get("/{org_id}/members", response_model=MemberListResponse)
def list_members(
    org_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemberListResponse:
    require_org_role(db, user, org_id)  # any member
    return orgs_service.list_members(db, org_id, limit=limit, offset=offset)

@router.patch("/{org_id}/members/{member_user_id}", response_model=MemberResponse)
def update_member(org_id: int, member_user_id: int, payload: MemberUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MemberResponse:
    require_org_role(db, user, org_id, "admin")
    return orgs_service.update_member(db, org_id, member_user_id, payload)

@router.post("/{org_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(org_id: int, payload: InviteCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InviteResponse:
    require_org_role(db, user, org_id, "admin")
    return invites_service.create_invite(db, org_id, user, payload)

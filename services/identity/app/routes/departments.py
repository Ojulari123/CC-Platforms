"""Department-scoped endpoints. None of them take a dept_id — it comes from the
caller's token, so you can only ever act on your own department."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Membership, User
from app.schemas.departments import DepartmentResponse, InviteCreate, InviteResponse, MemberListResponse, MemberResponse, MemberUpdate, TeamCreate, TeamResponse
from app.security import get_current_membership, get_current_user, require_role
from app.services import departments as dept_service
from app.services import invites as invites_service

router = APIRouter(prefix="/dept", tags=["department"])

admin_only = require_role("admin")

@router.get("", response_model=DepartmentResponse)
def get_department(membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.get_department(db, membership.dept_id)

@router.post("/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, membership: Membership = Depends(admin_only), db: Session = Depends(get_db)) -> TeamResponse:
    return dept_service.create_team(db, membership.dept_id, payload)

@router.get("/teams", response_model=list[TeamResponse])
def list_teams(membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[TeamResponse]:
    return dept_service.list_teams(db, membership.dept_id)

@router.get("/members", response_model=MemberListResponse)
def list_members(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> MemberListResponse:
    return dept_service.list_members(db, membership.dept_id, limit=limit, offset=offset)

@router.patch("/members/{member_user_id}", response_model=MemberResponse)
def update_member(member_user_id: int, payload: MemberUpdate, membership: Membership = Depends(admin_only), db: Session = Depends(get_db)) -> MemberResponse:
    return dept_service.update_member(db, membership.dept_id, member_user_id, payload)

@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteCreate, membership: Membership = Depends(admin_only), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> InviteResponse:
    return invites_service.create_invite(db, membership.dept_id, user, payload)

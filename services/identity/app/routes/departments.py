from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.departments import DepartmentCreate, DepartmentResponse, DepartmentUpdate, InviteCreate, InviteResponse, MemberAdd, MemberListResponse, MemberResponse, MemberTransfer, MemberUpdate, Role
from app.security import get_current_user, get_membership, require_dept_role, require_platform_admin
from app.services import departments as dept_service
from app.services import invites as invites_service

router = APIRouter(prefix="/departments", tags=["departments"])

dept_admin = require_dept_role("admin")
dept_member = require_dept_role()

@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.create_department(db, payload)

@router.get("", response_model=list[DepartmentResponse])
def list_departments(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DepartmentResponse]:
    return dept_service.list_departments(db)

@router.get("/{dept_id}", response_model=DepartmentResponse)
def get_department(dept_id: int, _: User = Depends(dept_member), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.get_department_response(db, dept_id)

@router.patch("/{dept_id}", response_model=DepartmentResponse)
def update_department(dept_id: int, payload: DepartmentUpdate, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.update_department(db, dept_id, payload)

@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(dept_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> None:
    dept_service.delete_department(db, dept_id)

@router.put("/{dept_id}/head/{head_user_id}", response_model=DepartmentResponse)
def set_department_head(dept_id: int, head_user_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.set_head(db, dept_id, head_user_id)

@router.delete("/{dept_id}/head", response_model=DepartmentResponse)
def clear_department_head(dept_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.set_head(db, dept_id, None)

@router.get("/{dept_id}/members", response_model=MemberListResponse)
def list_members(
    dept_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    role: Role | None = Query(default=None, description="Only members with this role"),
    team_id: int | None = Query(default=None, description="Only members on this team"),
    q: str | None = Query(default=None, description="Search first name, last name or email"),
    _: User = Depends(dept_member),
    db: Session = Depends(get_db),
) -> MemberListResponse:
    return dept_service.list_members(db, dept_id, limit=limit, offset=offset, role=role, team_id=team_id, q=q)

@router.post("/{dept_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(dept_id: int, payload: MemberAdd, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> MemberResponse:
    return dept_service.add_member(db, dept_id, payload.user_id, payload.role, payload.team_id)

@router.patch("/{dept_id}/members/{member_user_id}", response_model=MemberResponse)
def update_member(dept_id: int, member_user_id: int, payload: MemberUpdate, replacement_user_id: int | None = Query(default=None, description="Hand any team(s)/headship the demotion costs them to this person"), 
                  allow_unled: bool = Query(default=False, description="Demote anyway, leaving those without anyone in charge"), _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> MemberResponse:
    return dept_service.update_member(
        db, dept_id, member_user_id, payload,
        replacement_user_id=replacement_user_id,
        allow_unled=allow_unled,
    )

@router.patch("/{dept_id}/members/{member_user_id}/department", response_model=MemberResponse)
def transfer_member(dept_id: int, member_user_id: int, payload: MemberTransfer, replacement_user_id: int | None = Query(default=None, description="Hand any team(s)/headship the move costs them to this person"),
                    allow_unled: bool = Query(default=False, description="Move them anyway, leaving those without anyone in charge"), user: User = Depends(dept_admin), db: Session = Depends(get_db)) -> MemberResponse:
    # A move is add-to-target plus remove-from-source, so it needs what both of those
    # need: admin of the department they leave and of the one they join. Platform
    # admins clear dept_admin outright, so this only bites department admins.
    if not user.is_platform_admin:
        target = get_membership(db, user, payload.dept_id)
        if not target or target.role != "admin":
            raise HTTPException(status_code=403, detail="Requires the admin role in the department they are moving to")
    return dept_service.transfer_member(
        db, dept_id, member_user_id, payload.dept_id,
        replacement_user_id=replacement_user_id,
        allow_unled=allow_unled,
    )

@router.delete("/{dept_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(dept_id: int, member_user_id: int, replacement_user_id: int | None = Query(default=None, description="Hand their team(s)/headship to this person instead of leaving them empty"),
                  allow_unled: bool = Query(default=False, description="Proceed even though teams or the department will be left without a lead"), _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> None:
    dept_service.remove_member(
        db, dept_id, member_user_id,
        replacement_user_id=replacement_user_id,
        allow_unled=allow_unled,
    )

@router.post("/{dept_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(dept_id: int, payload: InviteCreate, user: User = Depends(dept_admin), db: Session = Depends(get_db)) -> InviteResponse:
    return invites_service.create_invite(db, dept_id, user, payload)

@router.get("/{dept_id}/invites", response_model=list[InviteResponse])
def list_invites(dept_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> list[InviteResponse]:
    return invites_service.list_pending_invites(db, dept_id)

@router.delete("/{dept_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(dept_id: int, invite_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> None:
    invites_service.revoke_invite(db, dept_id, invite_id)

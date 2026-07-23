"""Departments, their member roster, and their invites.

Every path names the department it acts on, and permission is checked against
THAT department. Someone can be an admin in Engineering and an engineer in Data
without either bleeding into the other. Teams are in routes/teams.py."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.departments import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    InviteCreate,
    InviteResponse,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
)
from app.security import get_current_user, require_dept_role, require_platform_admin
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
    """Any signed-in employee can see the list of departments — it's an internal
    org chart, not a secret. Acting on one still needs membership."""
    return dept_service.list_departments(db)

@router.get("/{dept_id}", response_model=DepartmentResponse)
def get_department(dept_id: int, _: User = Depends(dept_member), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.get_department(db, dept_id)

@router.patch("/{dept_id}", response_model=DepartmentResponse)
def update_department(dept_id: int, payload: DepartmentUpdate, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> DepartmentResponse:
    return dept_service.update_department(db, dept_id, payload)

@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(dept_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> None:
    dept_service.delete_department(db, dept_id)

@router.get("/{dept_id}/members", response_model=MemberListResponse)
def list_members(
    dept_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(dept_member),
    db: Session = Depends(get_db),
) -> MemberListResponse:
    return dept_service.list_members(db, dept_id, limit=limit, offset=offset)

@router.patch("/{dept_id}/members/{member_user_id}", response_model=MemberResponse)
def update_member(dept_id: int, member_user_id: int, payload: MemberUpdate, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> MemberResponse:
    return dept_service.update_member(db, dept_id, member_user_id, payload)

@router.delete("/{dept_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(dept_id: int, member_user_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> None:
    dept_service.remove_member(db, dept_id, member_user_id)

@router.post("/{dept_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(dept_id: int, payload: InviteCreate, user: User = Depends(dept_admin), db: Session = Depends(get_db)) -> InviteResponse:
    return invites_service.create_invite(db, dept_id, user, payload)

@router.get("/{dept_id}/invites", response_model=list[InviteResponse])
def list_invites(dept_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> list[InviteResponse]:
    return invites_service.list_pending_invites(db, dept_id)

@router.delete("/{dept_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(dept_id: int, invite_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> None:
    invites_service.revoke_invite(db, dept_id, invite_id)

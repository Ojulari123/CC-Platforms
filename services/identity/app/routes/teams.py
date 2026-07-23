"""Teams, nested under the department that owns them.

Team membership has its own endpoints rather than being a side-effect of
editing a department member — "put Dami on Platform" and "make Dami a manager"
are different operations and read better as different calls."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.departments import MemberResponse, TeamCreate, TeamResponse, TeamUpdate
from app.security import require_dept_role, require_team_manager
from app.services import teams as team_service

router = APIRouter(prefix="/departments/{dept_id}/teams", tags=["teams"])

dept_admin = require_dept_role("admin")
dept_member = require_dept_role()

@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(dept_id: int, payload: TeamCreate, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> TeamResponse:
    return team_service.create_team(db, dept_id, payload)

@router.get("", response_model=list[TeamResponse])
def list_teams(dept_id: int, _: User = Depends(dept_member), db: Session = Depends(get_db)) -> list[TeamResponse]:
    return team_service.list_teams(db, dept_id)

@router.get("/{team_id}", response_model=TeamResponse)
def get_team(dept_id: int, team_id: int, _: User = Depends(dept_member), db: Session = Depends(get_db)) -> TeamResponse:
    return team_service.get_team(db, dept_id, team_id)

@router.patch("/{team_id}", response_model=TeamResponse)
def update_team(dept_id: int, team_id: int, payload: TeamUpdate, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> TeamResponse:
    return team_service.update_team(db, dept_id, team_id, payload)

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(dept_id: int, team_id: int, _: User = Depends(dept_admin), db: Session = Depends(get_db)) -> None:
    team_service.delete_team(db, dept_id, team_id)

@router.get("/{team_id}/members", response_model=list[MemberResponse])
def list_team_members(dept_id: int, team_id: int, _: User = Depends(dept_member), db: Session = Depends(get_db)) -> list[MemberResponse]:
    return team_service.list_team_members(db, dept_id, team_id)

@router.put("/{team_id}/members/{member_user_id}", response_model=MemberResponse)
def add_team_member(dept_id: int, team_id: int, member_user_id: int, _: User = Depends(require_team_manager), db: Session = Depends(get_db)) -> MemberResponse:
    """PUT, not POST — assigning someone to a team is idempotent, so repeating
    the call lands in the same state instead of erroring."""
    return team_service.add_team_member(db, dept_id, team_id, member_user_id)

@router.delete("/{team_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(dept_id: int, team_id: int, member_user_id: int, _: User = Depends(require_team_manager), db: Session = Depends(get_db)) -> None:
    team_service.remove_team_member(db, dept_id, team_id, member_user_id)

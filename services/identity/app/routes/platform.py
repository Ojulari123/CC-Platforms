from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.departments import PlatformAdminResponse, UserAccountResponse
from app.security import require_platform_admin
from app.services import platform as platform_service

accounts_router = APIRouter(prefix="/platform/users", tags=["platform"])
router = APIRouter(prefix="/platform/admins", tags=["platform"])

@accounts_router.post("/{user_id}/deactivate", response_model=UserAccountResponse)
def deactivate_user(user_id: int, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> UserAccountResponse:
    return platform_service.deactivate_user(db, user_id, actor)

@accounts_router.post("/{user_id}/reactivate", response_model=UserAccountResponse)
def reactivate_user(user_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> UserAccountResponse:
    return platform_service.reactivate_user(db, user_id)

@router.get("", response_model=list[PlatformAdminResponse])
def list_platform_admins(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> list[PlatformAdminResponse]:
    return platform_service.list_platform_admins(db)

@router.put("/{user_id}", response_model=PlatformAdminResponse)
def grant_platform_admin(user_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> PlatformAdminResponse:
    return platform_service.grant_platform_admin(db, user_id)

@router.delete("/{user_id}", response_model=PlatformAdminResponse)
def revoke_platform_admin(user_id: int, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)) -> PlatformAdminResponse:
    return platform_service.revoke_platform_admin(db, user_id)

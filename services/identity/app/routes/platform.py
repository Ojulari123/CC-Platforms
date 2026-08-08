from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.schemas.departments import (
    PlatformAdminResponse,
    PlatformUserListResponse,
    PlatformUserResponse,
    UserAccountResponse,
)
from app.security import require_platform_admin
from app.services import platform as platform_service

accounts_router = APIRouter(prefix="/platform/users", tags=["platform"])
router = APIRouter(prefix="/platform/admins", tags=["platform"])

@accounts_router.get("", response_model=PlatformUserListResponse)
def list_users(
    q: str | None = Query(default=None, description="Search first name, last name or email"),
    is_active: bool | None = Query(default=None, description="Only active, or only deactivated, accounts"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformUserListResponse:
    """The workspace-wide user directory — every account across every department,
    for platform admins only. Distinct from a department roster, which is scoped
    to one department and shows role/team."""
    users, total = platform_service.list_users(db, q=q, is_active=is_active, limit=limit, offset=offset)
    return PlatformUserListResponse(
        items=[PlatformUserResponse.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )

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

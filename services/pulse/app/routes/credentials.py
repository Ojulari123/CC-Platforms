from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.auth import current_user
from app.db import get_db
from app.schemas.credentials import (
    BudgetList, BudgetResponse, BudgetUpsert, CredentialList, CredentialResponse,
    CredentialUpsert, EffectiveBudgetResponse, EffectiveCredentialResponse,
)
from app.services import credentials as credentials_service

router = APIRouter(prefix="/settings/credentials", tags=["credentials"])

@router.get("", response_model=CredentialList)
def list_credentials(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CredentialList:
    rows = credentials_service.list_credentials(db, user)
    return CredentialList(items=[CredentialResponse.model_validate(r) for r in rows])

@router.put("", response_model=CredentialResponse)
def upsert_credential(payload: CredentialUpsert, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CredentialResponse:
    return CredentialResponse.model_validate(credentials_service.upsert_credential(db, user, payload))

# Declared before /{credential_id}: a literal segment has to be matched first, or
# "effective" is read as a credential id.
@router.get("/effective", response_model=EffectiveCredentialResponse)
def effective_credential(provider: str | None = Query(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> EffectiveCredentialResponse:
    return EffectiveCredentialResponse(**credentials_service.effective_credential(db, user, provider=provider))

# The allowance sits on the credentials router rather than a surface of its own: a key
# and a cap are the same conversation, and the same scope and permission machinery
# answers both. Declared before /{credential_id} so "budgets" is not read as an id.
@router.get("/budgets", response_model=BudgetList)
def list_budgets(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> BudgetList:
    rows = credentials_service.list_budgets(db, user)
    return BudgetList(items=[BudgetResponse.model_validate(r) for r in rows])

@router.put("/budgets", response_model=BudgetResponse)
def upsert_budget(payload: BudgetUpsert, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> BudgetResponse:
    return BudgetResponse.model_validate(credentials_service.upsert_budget(db, user, payload))

@router.get("/budgets/effective", response_model=EffectiveBudgetResponse)
def effective_budget(user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> EffectiveBudgetResponse:
    return EffectiveBudgetResponse(**credentials_service.effective_budget(db, user))

@router.delete("/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    credentials_service.delete_budget(db, user, budget_id)

@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    credentials_service.delete_credential(db, user, credential_id)

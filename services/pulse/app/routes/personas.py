from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.schemas.personas import PersonaCreate, PersonaResponse, PersonaUpdate
from app.services import personas as personas_service

router = APIRouter(prefix="/personas", tags=["personas"])

@router.get("", response_model=Page[PersonaResponse])
def list_personas(page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[PersonaResponse]:
    items, total = personas_service.list_personas(db, user, limit=page.limit, offset=page.offset)
    return Page.of([PersonaResponse.model_validate(p) for p in items], total=total, params=page)

@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
def create_persona(payload: PersonaCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> PersonaResponse:
    return PersonaResponse.model_validate(personas_service.create_persona(db, user, payload))

@router.get("/{persona_id}", response_model=PersonaResponse)
def get_persona(persona_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> PersonaResponse:
    return PersonaResponse.model_validate(personas_service.get_persona(db, user, persona_id))

@router.patch("/{persona_id}", response_model=PersonaResponse)
def update_persona(persona_id: int, payload: PersonaUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> PersonaResponse:
    return PersonaResponse.model_validate(personas_service.update_persona(db, user, persona_id, payload))

@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(persona_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    personas_service.delete_persona(db, user, persona_id)

@router.put("/{persona_id}/default", response_model=PersonaResponse)
def set_default_persona(persona_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> PersonaResponse:
    return PersonaResponse.model_validate(personas_service.set_default(db, user, persona_id))

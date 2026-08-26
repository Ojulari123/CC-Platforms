from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.db import get_db
from app.services.provider_limits import ProviderRateLimited
from app.rate_limit import limiter, user_or_address_key
from app.schemas.chat import (
    ChatMessageResponse, ConversationCreate, ConversationDetailResponse,
    ConversationResponse, MessageCreate,
)
from app.services import chat as chat_service
from app.services.ai_provider import AIError
from app.services.chat import NoIndexedReposError
from app.services.llm_budget import BudgetExceededError

router = APIRouter(prefix="/chat/conversations", tags=["chat"])

@router.get("", response_model=Page[ConversationResponse])
def list_conversations(page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ConversationResponse]:
    rows, total = chat_service.list_conversations(db, user, limit=page.limit, offset=page.offset)
    return Page.of([ConversationResponse.model_validate(r) for r in rows], total=total, params=page)

@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ConversationResponse:
    return ConversationResponse.model_validate(chat_service.create_conversation(db, user, payload.title))

@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ConversationDetailResponse:
    return ConversationDetailResponse.model_validate(chat_service.get_conversation(db, user, conversation_id))

@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    chat_service.delete_conversation(db, user, conversation_id)

# One question is an embedding plus a generation, so the limit is about bursts; the real
# spend ceiling is the daily token budget, which every AI surface shares.
@router.post("/{conversation_id}/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/hour", key_func=user_or_address_key)
def send_message(request: Request, conversation_id: int, payload: MessageCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ChatMessageResponse:
    try:
        message = chat_service.answer(db, user, conversation_id=conversation_id, content=payload.content, indexed_repo_ids=payload.indexed_repo_ids)
    except NoIndexedReposError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except ProviderRateLimited as exc:
        # Busy, not broken. 503 with Retry-After is what tells a caller to come back
        # rather than that something went wrong.
        raise HTTPException(
            status_code=503,
            detail=f"The AI assistant is busy right now. Try again in about {max(1, round(exc.wait_seconds))} second(s).",
            headers={"Retry-After": str(max(1, round(exc.wait_seconds)))},
        )
    except AIError:
        # Not interpolated: an AIError carries the provider's own exception, which can
        # name request URLs, models and org ids. The provider module already logs it.
        raise HTTPException(status_code=502, detail="The AI assistant is unavailable right now. Please try again shortly.")
    return ChatMessageResponse.model_validate(message)

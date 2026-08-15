from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session
from crescent_core import TokenClaims, Page, PageParams, page_params
from app.auth import current_user
from app.db import get_db
from app.rate_limit import limiter, user_or_address_key
from app.models import ACTION_APPROVED, ACTION_CHANGES_REQUESTED, ACTION_REJECTED
from app.schemas.reports import (
    ApprovalResponse, CommentCreate, CommentResponse, CommentUpdate, DecisionRequest,
    GenerateRequest, ReportCreate, ReportResponse, ReportStatus, ReportUpdate,
)
from app.services import generation as generation_service, pdf as pdf_service, people, reports as reports_service
from app.services.generation import NoActivityError, ReportConflictError
from app.services.llm import LLMError

router = APIRouter(prefix="/reports", tags=["reports"])

def _named(model, rows, *pairs: tuple[str, str]) -> list:
    items = [model.model_validate(r) for r in rows]
    people.attach_names(items, *pairs)
    return items

def _named_report(report) -> ReportResponse:
    return _named(ReportResponse, [report], ("author_user_id", "author"))[0]

@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute", key_func=user_or_address_key)
def create_report(request: Request, payload: ReportCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.create_report(db, user, payload))

@router.post("/generate", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour", key_func=user_or_address_key)
def generate_report(request: Request, payload: GenerateRequest, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    try:
        return _named_report(generation_service.generate_report(db, user, payload.repo_id, payload.week_start))
    except NoActivityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ReportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LLMError:
        # Not interpolated: an LLMError carries the provider's own exception, which can
        # name request URLs, models and org ids. llm.py already logs it.
        raise HTTPException(status_code=502, detail="Report generation is unavailable right now. Please try again shortly.")

@router.get("", response_model=Page[ReportResponse])
def list_reports(repo_id: int | None = Query(default=None), dept_id: int | None = Query(default=None), author_user_id: int | None = Query(default=None), status: ReportStatus | None = Query(default=None, description="Filter by state; an unknown value is rejected with a 422"),
    page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ReportResponse]:
    items, total = reports_service.list_reports(
        db, user, limit=page.limit, offset=page.offset,
        repo_id=repo_id, dept_id=dept_id, author_user_id=author_user_id, status=status,
    )
    return Page.of(_named(ReportResponse, items, ("author_user_id", "author")), total=total, params=page)

@router.get("/review-queue", response_model=Page[ReportResponse])
def review_queue(status: ReportStatus | None = Query(default="submitted", description="Which state to show; defaults to those awaiting a decision"),
    page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ReportResponse]:
    items, total = reports_service.review_queue(db, user, limit=page.limit, offset=page.offset, status=status)
    return Page.of(_named(ReportResponse, items, ("author_user_id", "author")), total=total, params=page)

@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.get_report(db, user, report_id))

@router.get("/{report_id}/pdf")
def report_pdf(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    report = reports_service.get_report(db, user, report_id)
    body = pdf_service.render_report_pdf(db, report)
    filename = f"report-{report.id}-week-{report.week_start.isoformat()}.pdf"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@router.patch("/{report_id}", response_model=ReportResponse)
def update_report(report_id: int, payload: ReportUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.update_report(db, user, report_id, payload))

@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    reports_service.delete_report(db, user, report_id)

@router.post("/{report_id}/submit", response_model=ReportResponse)
def submit_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.submit_report(db, user, report_id))

@router.post("/{report_id}/approve", response_model=ReportResponse)
def approve_report(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.decide_report(db, user, report_id, ACTION_APPROVED, note=payload.note if payload else None))

@router.post("/{report_id}/reject", response_model=ReportResponse)
def reject_report(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.decide_report(db, user, report_id, ACTION_REJECTED, note=payload.note if payload else None))

@router.post("/{report_id}/request-changes", response_model=ReportResponse)
def request_changes(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return _named_report(reports_service.decide_report(db, user, report_id, ACTION_CHANGES_REQUESTED, note=payload.note if payload else None))

@router.get("/{report_id}/approvals", response_model=Page[ApprovalResponse])
def list_approvals(report_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ApprovalResponse]:
    items, total = reports_service.list_approvals(db, user, report_id, limit=page.limit, offset=page.offset)
    return Page.of(_named(ApprovalResponse, items, ("actor_user_id", "actor")), total=total, params=page)

@router.post("/{report_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(report_id: int, payload: CommentCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CommentResponse:
    return _named(CommentResponse, [reports_service.add_comment(db, user, report_id, payload.body)], ("author_user_id", "author"))[0]

@router.get("/{report_id}/comments", response_model=Page[CommentResponse])
def list_comments(report_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[CommentResponse]:
    items, total = reports_service.list_comments(db, user, report_id, limit=page.limit, offset=page.offset)
    return Page.of(_named(CommentResponse, items, ("author_user_id", "author")), total=total, params=page)

@router.patch("/{report_id}/comments/{comment_id}", response_model=CommentResponse)
def edit_comment(report_id: int, comment_id: int, payload: CommentUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CommentResponse:
    return _named(CommentResponse, [reports_service.edit_comment(db, user, report_id, comment_id, payload.body)], ("author_user_id", "author"))[0]

@router.delete("/{report_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(report_id: int, comment_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    reports_service.delete_comment(db, user, report_id, comment_id)

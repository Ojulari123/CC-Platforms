from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from crescent_core import TokenClaims, Page, PageParams, page_params
from app.auth import current_user
from app.db import get_db
from app.models import ACTION_APPROVED, ACTION_CHANGES_REQUESTED, ACTION_REJECTED
from app.schemas.reports import (
    ApprovalResponse, CommentCreate, CommentResponse, CommentUpdate, DecisionRequest,
    GenerateRequest, ReportCreate, ReportResponse, ReportStatus, ReportUpdate,
)
from app.services import generation as generation_service, pdf as pdf_service, reports as reports_service
from app.services.generation import NoActivityError, ReportConflictError
from app.services.llm import LLMError

router = APIRouter(prefix="/reports", tags=["reports"])

@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(payload: ReportCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.create_report(db, user, payload)

@router.post("/generate", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def generate_report(payload: GenerateRequest, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    """AI-draft the caller's weekly report for a repo from their synced activity.
    Additive to POST /reports (manual). Typed generation errors map to clean codes:
    empty week -> 422, already-decided report -> 409, LLM failure -> 502."""
    try:
        return generation_service.generate_report(db, user, payload.repo_id, payload.week_start)
    except NoActivityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ReportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Report generation is unavailable right now: {exc}")

@router.get("", response_model=Page[ReportResponse])
def list_reports(repo_id: int | None = Query(default=None), dept_id: int | None = Query(default=None), author_user_id: int | None = Query(default=None), status: ReportStatus | None = Query(default=None, description="Filter by state; an unknown value is rejected with a 422"),
    page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ReportResponse]:
    items, total = reports_service.list_reports(
        db, user, limit=page.limit, offset=page.offset,
        repo_id=repo_id, dept_id=dept_id, author_user_id=author_user_id, status=status,
    )
    return Page.of([ReportResponse.model_validate(r) for r in items], total=total, params=page)

@router.get("/review-queue", response_model=Page[ReportResponse])
def review_queue(status: ReportStatus | None = Query(default="submitted", description="Which state to show; defaults to those awaiting a decision"),
    page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ReportResponse]:
    items, total = reports_service.review_queue(db, user, limit=page.limit, offset=page.offset, status=status)
    return Page.of([ReportResponse.model_validate(r) for r in items], total=total, params=page)

@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.get_report(db, user, report_id)

@router.get("/{report_id}/pdf")
def report_pdf(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """Download the report as a PDF. Gated behind the same read permission as viewing
    it — get_report raises 404/403 if you can't see it — then rendered with reportlab."""
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
    return reports_service.update_report(db, user, report_id, payload)

@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    reports_service.delete_report(db, user, report_id)

@router.post("/{report_id}/submit", response_model=ReportResponse)
def submit_report(report_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.submit_report(db, user, report_id)

@router.post("/{report_id}/approve", response_model=ReportResponse)
def approve_report(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.decide_report(db, user, report_id, ACTION_APPROVED, note=payload.note if payload else None)

@router.post("/{report_id}/reject", response_model=ReportResponse)
def reject_report(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.decide_report(db, user, report_id, ACTION_REJECTED, note=payload.note if payload else None)

# Send it back to the author to edit and re-submit.
@router.post("/{report_id}/request-changes", response_model=ReportResponse)
def request_changes(report_id: int, payload: DecisionRequest | None = None, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ReportResponse:
    return reports_service.decide_report(db, user, report_id, ACTION_CHANGES_REQUESTED, note=payload.note if payload else None)

@router.get("/{report_id}/approvals", response_model=Page[ApprovalResponse])
def list_approvals(report_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[ApprovalResponse]:
    items, total = reports_service.list_approvals(db, user, report_id, limit=page.limit, offset=page.offset)
    return Page.of([ApprovalResponse.model_validate(a) for a in items], total=total, params=page)

@router.post("/{report_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(report_id: int, payload: CommentCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CommentResponse:
    return reports_service.add_comment(db, user, report_id, payload.body)

@router.get("/{report_id}/comments", response_model=Page[CommentResponse])
def list_comments(report_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[CommentResponse]:
    items, total = reports_service.list_comments(db, user, report_id, limit=page.limit, offset=page.offset)
    return Page.of([CommentResponse.model_validate(c) for c in items], total=total, params=page)

# Edit / delete your own comment. edited_at is stamped on edit.
@router.patch("/{report_id}/comments/{comment_id}", response_model=CommentResponse)
def edit_comment(report_id: int, comment_id: int, payload: CommentUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> CommentResponse:
    return reports_service.edit_comment(db, user, report_id, comment_id, payload.body)

@router.delete("/{report_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(report_id: int, comment_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    reports_service.delete_comment(db, user, report_id, comment_id)

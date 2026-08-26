from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import (
    ACTION_APPROVED, ACTION_CHANGES_REQUESTED, ACTION_REJECTED, ACTION_SUBMITTED, REPORT_KIND_WEEKLY,
    STATUS_APPROVED, STATUS_CHANGES_REQUESTED, STATUS_DRAFT, STATUS_REJECTED, STATUS_SUBMITTED,
    Approval, Comment, Report, Repository,
)
from app.schemas.reports import ReportCreate, ReportUpdate
from app.services.email import notify_report_ready
from app.services.repositories import may_write_on_repo

_ACTION_TO_STATUS = {
    ACTION_APPROVED: STATUS_APPROVED,
    ACTION_REJECTED: STATUS_REJECTED,
    ACTION_CHANGES_REQUESTED: STATUS_CHANGES_REQUESTED,
}
_EDITABLE = (STATUS_DRAFT, STATUS_CHANGES_REQUESTED)

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

def _get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report

def _repo_of(db: Session, report: Report) -> Repository | None:
    # An ad-hoc report on an untracked repository has no repo_id at all, and db.get with
    # a null key warns rather than simply missing.
    return db.get(Repository, report.repo_id) if report.repo_id is not None else None

def _can_read(user: TokenClaims, report: Report, repo: Repository | None) -> bool:
    if user.is_platform_admin:
        return True
    if report.author_user_id == user.user_id:
        return True
    if repo is not None and user.user_id in (repo.lead_user_id, repo.deputy_user_id):
        return True
    return report.dept_id is not None and user.role_in(report.dept_id) == "admin"

def _require_can_read(user: TokenClaims, report: Report, repo: Repository | None) -> None:
    if not _can_read(user, report, repo):
        raise HTTPException(status_code=403, detail="You don't have access to this report")

def _can_approve(user: TokenClaims, report: Report, repo: Repository | None) -> bool:
    # Has to come first, or a platform admin (or a lead reporting on their own repo)
    # self-approves.
    if report.author_user_id == user.user_id:
        return False
    if user.is_platform_admin:
        return True
    if repo is not None and user.user_id in (repo.lead_user_id, repo.deputy_user_id):
        return True
    return report.dept_id is not None and user.role_in(report.dept_id) == "admin"

def _require_author(user: TokenClaims, report: Report, verb: str) -> None:
    if report.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail=f"Only the author can {verb} this report")

def _has_content(report: Report) -> bool:
    return any((s or "").strip() for s in (report.summary_manager, report.summary_exec, report.next_week_goals))

def create_report(db: Session, user: TokenClaims, payload: ReportCreate) -> Report:
    repo = db.get(Repository, payload.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not may_write_on_repo(db, user, repo):
        raise HTTPException(
            status_code=403,
            detail=(
                "You have no synced activity in this repo. Reports are for repos "
                "you've worked in. If your GitHub isn't connected or synced yet, "
                "do that first."
            ),
        )
    week = _monday(payload.week_start or date.today())
    report = Report(
        author_user_id=user.user_id,
        subject_user_id=user.user_id,  # a weekly report is about the person writing it
        repo_id=repo.id,
        repo_full_name=repo.full_name,
        dept_id=repo.dept_id,  # taken from the repo, never from the author
        kind=REPORT_KIND_WEEKLY,
        week_start=week,
        range_start=week,
        range_end=week + timedelta(days=6),
        status=STATUS_DRAFT,
        summary_manager=payload.summary_manager,
        summary_exec=payload.summary_exec,
        next_week_goals=payload.next_week_goals,
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a report for this repo for the week of {week.isoformat()}")
    db.refresh(report)
    return report

def report_subject_ids(report: Report) -> list[int]:
    """Who a report is about. The child rows when it covers several contributors,
    otherwise the single subject on the report itself."""
    if report.subjects:
        return [s.subject_user_id for s in report.subjects if s.subject_user_id is not None]
    return [report.subject_user_id] if report.subject_user_id is not None else []

def list_reports(db: Session, user: TokenClaims, limit: int, offset: int, repo_id: int | None = None, dept_id: int | None = None, author_user_id: int | None = None, status: str | None = None) -> tuple[list[Report], int]:
    wide = user.is_platform_admin
    if not wide and repo_id is not None:
        repo = db.get(Repository, repo_id)
        if repo is not None and (
            user.user_id in (repo.lead_user_id, repo.deputy_user_id)
            or (repo.dept_id is not None and user.role_in(repo.dept_id) == "admin")
        ):
            wide = True
    if not wide and dept_id is not None and user.role_in(dept_id) == "admin":
        wide = True

    filters = []
    if not wide:
        filters.append(Report.author_user_id == user.user_id)
    if repo_id is not None:
        filters.append(Report.repo_id == repo_id)
    if dept_id is not None:
        filters.append(Report.dept_id == dept_id)
    if author_user_id is not None:
        filters.append(Report.author_user_id == author_user_id)
    if status is not None:
        filters.append(Report.status == status)

    base = select(Report).where(*filters) if filters else select(Report)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Report.week_start.desc(), Report.id.desc()).limit(limit).offset(offset))
    return list(rows), total

def review_queue(db: Session, user: TokenClaims, limit: int, offset: int, status: str | None = STATUS_SUBMITTED) -> tuple[list[Report], int]:
    filters = [Report.author_user_id != user.user_id]
    if status:
        filters.append(Report.status == status)
    if not user.is_platform_admin:
        approver_repo_ids = select(Repository.id).where(
            or_(Repository.lead_user_id == user.user_id, Repository.deputy_user_id == user.user_id)
        )
        scope = [Report.repo_id.in_(approver_repo_ids)]
        admin_dept_ids = [m.dept_id for m in user.memberships if m.role == "admin"]
        if admin_dept_ids:
            scope.append(Report.dept_id.in_(admin_dept_ids))
        filters.append(or_(*scope))

    base = select(Report).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Report.week_start.desc(), Report.id.desc()).limit(limit).offset(offset))
    return list(rows), total

def get_report(db: Session, user: TokenClaims, report_id: int) -> Report:
    report = _get_report(db, report_id)
    _require_can_read(user, report, _repo_of(db, report))
    return report

def update_report(db: Session, user: TokenClaims, report_id: int, payload: ReportUpdate) -> Report:
    report = _get_report(db, report_id)
    _require_author(user, report, "edit")
    if report.status not in _EDITABLE:
        raise HTTPException(status_code=409, detail=f"A {report.status} report can't be edited")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(report, field, value)
    db.commit()
    db.refresh(report)
    return report

def submit_report(db: Session, user: TokenClaims, report_id: int) -> Report:
    report = _get_report(db, report_id)
    _require_author(user, report, "submit")
    if report.status not in _EDITABLE:
        raise HTTPException(status_code=409, detail=f"A {report.status} report can't be submitted")
    if not _has_content(report):
        raise HTTPException(status_code=422, detail="Cannot submit an empty report. Generate or write summaries first.")
    report.status = STATUS_SUBMITTED
    db.add(Approval(report_id=report.id, actor_user_id=user.user_id, action=ACTION_SUBMITTED))
    db.commit()
    db.refresh(report)
    # Best-effort: after the commit so a notification problem can never block or roll
    # back the submission. notify_report_ready swallows its own errors.
    notify_report_ready(report)
    return report

def decide_report(db: Session, user: TokenClaims, report_id: int, action: str, note: str | None = None) -> Report:
    report = _get_report(db, report_id)
    if report.author_user_id == user.user_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "You can't decide your own report. Ask this repo's lead or deputy, an "
                "admin of its department, or another platform admin to review it. If "
                "the repo has none of those, ask a platform admin to file it under a "
                "department or name a lead."
            ),
        )
    if not _can_approve(user, report, _repo_of(db, report)):
        raise HTTPException(status_code=403, detail="Only this repo's lead or deputy (or a department admin) can decide this report")
    if report.status != STATUS_SUBMITTED:
        raise HTTPException(status_code=409, detail=f"Only a submitted report can be decided (this one is {report.status})")
    report.status = _ACTION_TO_STATUS[action]
    db.add(Approval(report_id=report.id, actor_user_id=user.user_id, action=action, note=note))
    db.commit()
    db.refresh(report)
    return report

def delete_report(db: Session, user: TokenClaims, report_id: int) -> None:
    report = _get_report(db, report_id)
    if report.status != STATUS_DRAFT:
        raise HTTPException(status_code=409, detail="A submitted report is part of the record and can't be deleted")
    if report.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Only the author can delete their own draft")
    db.delete(report)
    db.commit()

def list_approvals(db: Session, user: TokenClaims, report_id: int, limit: int, offset: int) -> tuple[list[Approval], int]:
    report = _get_report(db, report_id)
    _require_can_read(user, report, _repo_of(db, report))
    base = select(Approval).where(Approval.report_id == report.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Approval.created_at, Approval.id).limit(limit).offset(offset))
    return list(rows), total

def _get_comment(db: Session, report_id: int, comment_id: int) -> Comment:
    comment = db.get(Comment, comment_id)
    if not comment or comment.report_id != report_id:
        raise HTTPException(status_code=404, detail="Comment not found on this report")
    return comment

def add_comment(db: Session, user: TokenClaims, report_id: int, body: str) -> Comment:
    report = _get_report(db, report_id)
    _require_can_read(user, report, _repo_of(db, report))
    comment = Comment(report_id=report.id, author_user_id=user.user_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment

def edit_comment(db: Session, user: TokenClaims, report_id: int, comment_id: int, body: str) -> Comment:
    comment = _get_comment(db, report_id, comment_id)
    if comment.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own comment")
    comment.body = body
    comment.edited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(comment)
    return comment

def delete_comment(db: Session, user: TokenClaims, report_id: int, comment_id: int) -> None:
    comment = _get_comment(db, report_id, comment_id)
    if comment.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comment")
    db.delete(comment)
    db.commit()

def list_comments(db: Session, user: TokenClaims, report_id: int, limit: int, offset: int) -> tuple[list[Comment], int]:
    report = _get_report(db, report_id)
    _require_can_read(user, report, _repo_of(db, report))
    base = select(Comment).where(Comment.report_id == report.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Comment.created_at, Comment.id).limit(limit).offset(offset))
    return list(rows), total

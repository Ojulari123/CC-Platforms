"""Report domain: the draft → submit → approve flow, the append-only approval
history, and flat comments.

Every authorization decision is made purely from the caller's token claims
(`TokenClaims`) — Pulse never reads identity's database. The rules come from the
decisions doc (Decision 6):

- **Read** a report: the author; anyone with the `manager` or `admin` role in the
  report's department (department-wide visibility); a platform admin.
- **Approve / reject / request changes**: the report's team lead, a department `admin` (the fallback for an absent
  lead), or a platform admin. Note the manager *role* alone can read but not
  approve — only the *named team lead* signs off.
- **Create / edit / submit**: the author, and only their own report.
"""
from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import (
    ACTION_APPROVED, ACTION_CHANGES_REQUESTED, ACTION_REJECTED, ACTION_SUBMITTED,
    STATUS_APPROVED, STATUS_CHANGES_REQUESTED, STATUS_DRAFT, STATUS_REJECTED, STATUS_SUBMITTED,
    Approval, Comment, Report,
)
from app.schemas.reports import ReportCreate, ReportUpdate

_ACTION_TO_STATUS = {
    ACTION_APPROVED: STATUS_APPROVED,
    ACTION_REJECTED: STATUS_REJECTED,
    ACTION_CHANGES_REQUESTED: STATUS_CHANGES_REQUESTED,
}
_EDITABLE = (STATUS_DRAFT, STATUS_CHANGES_REQUESTED)


def _monday(d: date) -> date:
    """The Monday of d's week, so 'one report per week' has a single canonical key
    no matter which day the report was opened on."""
    return d - timedelta(days=d.weekday())


def _get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ── permission checks (token-only) ────────────────────────────────────────────
def _can_read(user: TokenClaims, report: Report) -> bool:
    if user.is_platform_admin:
        return True
    if report.author_user_id == user.user_id:
        return True
    return user.role_in(report.dept_id) in ("manager", "admin")

def _require_can_read(user: TokenClaims, report: Report) -> None:
    if not _can_read(user, report):
        raise HTTPException(status_code=403, detail="You don't have access to this report")

def _can_approve(user: TokenClaims, report: Report) -> bool:
    if user.is_platform_admin:
        return True
    if user.role_in(report.dept_id) == "admin":  # department admin covers an absent lead
        return True
    return report.team_id is not None and user.leads_team(report.team_id)

def _require_author(user: TokenClaims, report: Report, verb: str) -> None:
    if report.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail=f"Only the author can {verb} this report")

# ── operations ────────────────────────────────────────────────────────────────
def create_report(db: Session, user: TokenClaims, payload: ReportCreate) -> Report:
    if not user.is_platform_admin and not user.is_member_of(payload.dept_id):
        raise HTTPException(status_code=403, detail="Not a member of this department")
    week = _monday(payload.week_start or date.today())
    report = Report(
        author_user_id=user.user_id,
        dept_id=payload.dept_id,
        team_id=user.team_in(payload.dept_id),
        week_start=week,
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
        raise HTTPException(status_code=409, detail=f"You already have a report for the week of {week.isoformat()}")
    db.refresh(report)
    return report

def list_reports(db: Session,user: TokenClaims, dept_id: int, limit: int, offset: int, team_id: int | None = None, author_user_id: int | None = None, status: str | None = None) -> tuple[list[Report], int]:
    """Reports in one department the caller can see. Managers/admins (and platform
    admins) see the whole department; everyone else sees only their own, so the
    author filter can narrow that set but never widen it."""
    if not user.is_platform_admin and not user.is_member_of(dept_id):
        raise HTTPException(status_code=403, detail="Not a member of this department")

    filters = [Report.dept_id == dept_id]
    dept_wide = user.is_platform_admin or user.role_in(dept_id) in ("manager", "admin")
    if not dept_wide:
        filters.append(Report.author_user_id == user.user_id)
    if author_user_id is not None:
        filters.append(Report.author_user_id == author_user_id)
    if team_id is not None:
        filters.append(Report.team_id == team_id)
    if status is not None:
        filters.append(Report.status == status)

    base = select(Report).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Report.week_start.desc(), Report.id.desc()).limit(limit).offset(offset)
    )
    return list(rows), total

def get_report(db: Session, user: TokenClaims, report_id: int) -> Report:
    report = _get_report(db, report_id)
    _require_can_read(user, report)
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
    report.status = STATUS_SUBMITTED
    db.add(Approval(report_id=report.id, actor_user_id=user.user_id, action=ACTION_SUBMITTED))
    db.commit()
    db.refresh(report)
    return report

def decide_report(db: Session, user: TokenClaims, report_id: int, action: str, note: str | None = None) -> Report:
    """Approve / reject / request-changes on a submitted report. One approver:
    the report's team lead, with a department admin (or platform admin) as the
    fallback for an absent lead."""
    report = _get_report(db, report_id)
    if not _can_approve(user, report):
        raise HTTPException(status_code=403, detail="Only this team's lead (or a department admin) can decide this report")
    if report.status != STATUS_SUBMITTED:
        raise HTTPException(status_code=409, detail=f"Only a submitted report can be decided (this one is {report.status})")
    report.status = _ACTION_TO_STATUS[action]
    db.add(Approval(report_id=report.id, actor_user_id=user.user_id, action=action, note=note))
    db.commit()
    db.refresh(report)
    return report

def delete_report(db: Session, user: TokenClaims, report_id: int) -> None:
    """Delete a report and, by cascade, its comments. Only a **draft** can be
    deleted, and only by its author — it's their own unsent work.

    Once a report is submitted it becomes part of the permanent record and can
    never be deleted, by anyone, including admins. That immutability is the whole
    point: a report that was seen and approved/rejected can't quietly disappear."""
    report = _get_report(db, report_id)
    if report.status != STATUS_DRAFT:
        raise HTTPException(status_code=409, detail="A submitted report is part of the record and can't be deleted")
    if report.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Only the author can delete their own draft")
    db.delete(report)
    db.commit()

def list_approvals(db: Session, user: TokenClaims, report_id: int, limit: int, offset: int) -> tuple[list[Approval], int]:
    report = _get_report(db, report_id)
    _require_can_read(user, report)
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
    _require_can_read(user, report)  # if you can see the report, you can comment on it
    comment = Comment(report_id=report.id, author_user_id=user.user_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment

def edit_comment(db: Session, user: TokenClaims, report_id: int, comment_id: int, body: str) -> Comment:
    """Edit your own comment. Stamps edited_at so the UI can show '(edited)'."""
    comment = _get_comment(db, report_id, comment_id)
    if comment.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own comment")
    comment.body = body
    comment.edited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(comment)
    return comment

def delete_comment(db: Session, user: TokenClaims, report_id: int, comment_id: int) -> None:
    """Delete your own comment."""
    comment = _get_comment(db, report_id, comment_id)
    if comment.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comment")
    db.delete(comment)
    db.commit()

def list_comments(db: Session, user: TokenClaims, report_id: int, limit: int, offset: int) -> tuple[list[Comment], int]:
    report = _get_report(db, report_id)
    _require_can_read(user, report)
    base = select(Comment).where(Comment.report_id == report.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Comment.created_at, Comment.id).limit(limit).offset(offset))
    return list(rows), total

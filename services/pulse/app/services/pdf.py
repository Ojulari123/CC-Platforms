from datetime import timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session
from app.models import (STATUS_APPROVED, STATUS_CHANGES_REQUESTED, STATUS_DRAFT, STATUS_REJECTED, STATUS_SUBMITTED, Report)
from app.services.generation import _collect_week_activity
from app.services.identity_client import resolve_profiles_safe

_STATUS_COLORS = {
    STATUS_DRAFT: colors.HexColor("#6b7280"),
    STATUS_SUBMITTED: colors.HexColor("#2563eb"),
    STATUS_APPROVED: colors.HexColor("#16a34a"),
    STATUS_REJECTED: colors.HexColor("#dc2626"),
    STATUS_CHANGES_REQUESTED: colors.HexColor("#d97706"),
}
_EMPTY = "— not generated —"

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("PulseTitle", parent=base["Title"], fontSize=18, spaceAfter=4, alignment=TA_LEFT),
        "meta": ParagraphStyle("PulseMeta", parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#6b7280")),
        "heading": ParagraphStyle("PulseHeading", parent=base["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4),
        "body": ParagraphStyle("PulseBody", parent=base["Normal"], fontSize=10, leading=14),
        "badge": ParagraphStyle("PulseBadge", parent=base["Normal"], fontSize=11, textColor=colors.white, alignment=TA_LEFT),
    }

def _status_badge(status: str, styles: dict) -> Table:
    color = _STATUS_COLORS.get(status, colors.HexColor("#6b7280"))
    label = Paragraph(f"<b>{status.replace('_', ' ').upper()}</b>", styles["badge"])
    tbl = Table([[label]], colWidths=[2.2 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl

def _section(heading: str, text: str | None, styles: list, s: dict) -> None:
    styles.append(Paragraph(heading, s["heading"]))
    body = (text or "").strip() or _EMPTY
    # reportlab treats newlines as spaces; turn them into <br/> so goals lists survive.
    # Escape first: the <br/> is the template's markup, everything else is data.
    styles.append(Paragraph(escape(body).replace("\n", "<br/>"), s["body"]))

def _activity_table(counts: dict, s: dict) -> Table:
    rows = [
        [Paragraph("<b>Commits</b>", s["body"]), Paragraph("<b>Pull Requests</b>", s["body"]),
         Paragraph("<b>Reviews</b>", s["body"]), Paragraph("<b>Issues</b>", s["body"])],
        [str(counts["commits"]), str(counts["pull_requests"]), str(counts["reviews"]), str(counts["issues"])],
    ]
    tbl = Table(rows, colWidths=[1.5 * inch] * 4)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl

def _author_label(report: Report) -> str:
    profile = resolve_profiles_safe([report.author_user_id]).get(report.author_user_id)
    if profile is None:
        return f"Engineer #{report.author_user_id}"
    # The name is identity's data, not ours; escape it before it becomes reportlab markup.
    return escape(f"{profile['first_name']} {profile['last_name']}") + f" (#{report.author_user_id})"

def render_report_pdf(db: Session, report: Report) -> bytes:
    s = _styles()
    repo = report.repository
    repo_name = repo.full_name if repo is not None else f"repo #{report.repo_id}"
    week_start = report.week_start
    week_end = week_start + timedelta(days=6)

    flow: list = []
    flow.append(Paragraph(f"Weekly Report — {escape(repo_name)}", s["title"]))
    flow.append(Paragraph(
        f"{_author_label(report)} &nbsp;·&nbsp; "
        f"Week of {week_start.isoformat()} ({week_start.isoformat()} → {week_end.isoformat()})",
        s["meta"],
    ))
    flow.append(Spacer(1, 8))
    flow.append(_status_badge(report.status, s))

    activity = _collect_week_activity(db, report.author_user_id, report.repo_id, week_start)
    flow.append(Paragraph("Activity this week", s["heading"]))
    flow.append(_activity_table(activity["counts"], s))

    _section("Manager Summary", report.summary_manager, flow, s)
    _section("Executive Summary", report.summary_exec, flow, s)
    _section("Next-Week Goals", report.next_week_goals, flow, s)

    if report.generated_at is not None:
        flow.append(Spacer(1, 16))
        flow.append(Paragraph(f"Generated {report.generated_at.isoformat()}", s["meta"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title=f"Pulse report {report.id}",
    )
    doc.build(flow)
    return buffer.getvalue()

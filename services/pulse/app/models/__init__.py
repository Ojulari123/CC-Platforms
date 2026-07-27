from sqlalchemy import Column, Integer, String, Text, Date, TIMESTAMP, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.db import Base

# Report lifecycle. draft → submitted → (approved | rejected | changes_requested).
# changes_requested goes back to the author, who edits and re-submits.
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CHANGES_REQUESTED = "changes_requested"

# An approval-history entry records the action that produced a status. The
# author "submitted"; the team lead "approved" / "rejected" / "changes_requested".
ACTION_SUBMITTED = "submitted"
ACTION_APPROVED = "approved"
ACTION_REJECTED = "rejected"
ACTION_CHANGES_REQUESTED = "changes_requested"

class Report(Base):
    """One engineer's weekly report. People and teams are referenced by id only
    (author_user_id, dept_id, team_id) — Pulse never stores names/emails, and
    never reads identity's database (CLAUDE.md rule 3). The AI-drafted summary
    fields are plain editable text for now; the generation step is Week 4."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    author_user_id = Column(Integer, nullable=False, index=True)
    dept_id = Column(Integer, nullable=False, index=True)
    team_id = Column(Integer, nullable=True, index=True)
    # The Monday of the report week. One report per author per week.
    week_start = Column(Date, nullable=False)
    status = Column(String(30), nullable=False, server_default=STATUS_DRAFT, default=STATUS_DRAFT)
    summary_manager = Column(Text, nullable=True)
    summary_exec = Column(Text, nullable=True)
    next_week_goals = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    approvals = relationship("Approval", back_populates="report", cascade="all, delete-orphan", order_by="Approval.created_at")
    comments = relationship("Comment", back_populates="report", cascade="all, delete-orphan", order_by="Comment.created_at")

    __table_args__ = (UniqueConstraint("author_user_id", "week_start", name="uq_report_author_week"),)

class Approval(Base):
    """Append-only history of what happened to a report — who did what, when, and
    why. Rows are never updated or deleted; Report.status is the denormalised
    'current state' derived from the latest entry, kept for fast listing."""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    report = relationship("Report", back_populates="approvals")

class Comment(Base):
    """A flat comment on a report — no threading (a deliberate v1 simplification;
    see docs/erd.md). Authored by a user referenced by id."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(TIMESTAMP(timezone=True), nullable=True)

    report = relationship("Report", back_populates="comments")

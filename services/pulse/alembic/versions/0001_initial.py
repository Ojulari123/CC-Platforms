"""initial: reports, approvals, comments

The Pulse reporting domain. People and teams are referenced by id only — there
are no foreign keys into identity (separate database, CLAUDE.md rule 3).

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("dept_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("summary_manager", sa.Text(), nullable=True),
        sa.Column("summary_exec", sa.Text(), nullable=True),
        sa.Column("next_week_goals", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("author_user_id", "week_start", name="uq_report_author_week"),
    )
    op.create_index("ix_reports_author_user_id", "reports", ["author_user_id"])
    op.create_index("ix_reports_dept_id", "reports", ["dept_id"])
    op.create_index("ix_reports_team_id", "reports", ["team_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_approvals_report_id", "approvals", ["report_id"])

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_comments_report_id", "comments", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_report_id", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_approvals_report_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_reports_team_id", table_name="reports")
    op.drop_index("ix_reports_dept_id", table_name="reports")
    op.drop_index("ix_reports_author_user_id", table_name="reports")
    op.drop_table("reports")

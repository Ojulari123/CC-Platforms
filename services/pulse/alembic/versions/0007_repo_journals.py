"""per-repo journals, their AI rollups, and a token ledger that isn't report-only

Journals are free-text notes a repo's members leave for each other, and a rollup is
one AI readout over the last of them. Rollups cost tokens like report generation
does, so `llm_usage` grows a `kind`: without it, a row with no report_id is spend
nobody can attribute to a surface. report_id has been nullable since 0004, so
nothing there needs altering. Every existing row is a report generation, hence the
server default.

Revision ID: 0007_repo_journals
Revises: 0006_report_prompt_version
Create Date: 2026-08-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_repo_journals"
down_revision: Union[str, None] = "0006_report_prompt_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repo_journals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("edited_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_journals_repo_id", "repo_journals", ["repo_id"])
    op.create_index("ix_repo_journals_author_user_id", "repo_journals", ["author_user_id"])

    op.create_table(
        "journal_rollups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("covers_from", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("covers_to", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("generated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_rollups_repo_id", "journal_rollups", ["repo_id"])
    op.create_index("ix_journal_rollups_generated_by_user_id", "journal_rollups", ["generated_by_user_id"])

    op.add_column("llm_usage", sa.Column("kind", sa.String(30), server_default="report", nullable=False))


def downgrade() -> None:
    op.drop_column("llm_usage", "kind")

    op.drop_index("ix_journal_rollups_generated_by_user_id", table_name="journal_rollups")
    op.drop_index("ix_journal_rollups_repo_id", table_name="journal_rollups")
    op.drop_table("journal_rollups")

    op.drop_index("ix_repo_journals_author_user_id", table_name="repo_journals")
    op.drop_index("ix_repo_journals_repo_id", table_name="repo_journals")
    op.drop_table("repo_journals")

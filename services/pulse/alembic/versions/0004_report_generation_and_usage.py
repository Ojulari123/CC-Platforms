"""report generation stamp + platform-admin token-usage ledger

Week 4 adds a generate step (POST /reports/generate). A generated report stamps
`generated_at` (nullable — a hand-written report leaves it null). Token usage does NOT
live on the report; it rolls up into `llm_usage`, a per-generation ledger the platform
admin reads to know when to top up the LLM account. Only one model is ever in use, so
neither table records which model produced a draft.

Revision ID: 0004_report_generation_and_usage
Revises: 0003_repo_centric_reporting
Create Date: 2026-08-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_report_generation_and_usage"
down_revision: Union[str, None] = "0003_repo_centric_reporting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_report_id", "llm_usage", ["report_id"])
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_user_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_report_id", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_column("reports", "generated_at")

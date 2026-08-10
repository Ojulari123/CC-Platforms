"""record which prompt produced a generated draft

prompts.PROMPT_VERSION existed but was stored nowhere, so "which prompt wrote this?"
was unanswerable. Nullable: reports written by hand never had a prompt, and reports
generated before this migration can't be attributed after the fact.

Revision ID: 0006_report_prompt_version
Revises: 0005_drop_commit_line_counts
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_report_prompt_version"
down_revision: Union[str, None] = "0005_drop_commit_line_counts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("prompt_version", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "prompt_version")

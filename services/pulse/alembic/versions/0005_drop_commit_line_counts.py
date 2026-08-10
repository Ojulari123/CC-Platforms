"""drop commits.additions / commits.deletions

Declared in 0002 but never populated: GitHub's commit *list* endpoint doesn't return
line counts, so filling them costs one extra API call per commit against a shared rate
limit — for a statistic nothing in Pulse reads. Dropped rather than left half-built.

Revision ID: 0005_drop_commit_line_counts
Revises: 0004_report_generation_and_usage
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_drop_commit_line_counts"
down_revision: Union[str, None] = "0004_report_generation_and_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("commits", "additions")
    op.drop_column("commits", "deletions")


def downgrade() -> None:
    # Nullable on the way back, matching 0002 — the values were never written, so
    # there is nothing to restore.
    op.add_column("commits", sa.Column("deletions", sa.Integer(), nullable=True))
    op.add_column("commits", sa.Column("additions", sa.Integer(), nullable=True))

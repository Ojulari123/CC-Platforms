"""datasets

People are referenced by identity `user_id` only — no foreign key into identity
(separate database, CLAUDE.md rule 3). Raw CSV text lives in `content`; no storage volume.

Revision ID: 0001_datasets
Revises:
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_datasets"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("is_sample", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("original_filename", sa.String(400), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("columns", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_datasets_owner_user_id", "datasets", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_datasets_owner_user_id", table_name="datasets")
    op.drop_table("datasets")

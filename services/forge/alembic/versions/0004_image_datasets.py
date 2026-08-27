"""image datasets: a kind marker and a place to keep the archive bytes

An image dataset is a ZIP with one folder per class. The validated archive goes in
`content_blob` and a JSON manifest (classes, counts, entry names) goes in `content`,
which keeps that column NOT NULL and leaves every existing CSV row untouched.

`kind` defaults to 'tabular' at the database level, so rows written before this
migration keep meaning exactly what they meant.

Revision ID: 0004_image_datasets
Revises: 0003_workflows
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_image_datasets"
down_revision: Union[str, None] = "0003_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("kind", sa.String(length=20), server_default="tabular", nullable=False))
    op.add_column("datasets", sa.Column("content_blob", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "content_blob")
    op.drop_column("datasets", "kind")

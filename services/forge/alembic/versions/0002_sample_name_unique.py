"""sample name partial unique index

Stops concurrent worker boots double-seeding samples: the predicate excludes user
uploads, so duplicate private names stay allowed. Matches Dataset.__table_args__.

Revision ID: 0002_sample_name_unique
Revises: 0001_datasets
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sample_name_unique"
down_revision: Union[str, None] = "0001_datasets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_sample_name",
        "datasets",
        ["name"],
        unique=True,
        sqlite_where=sa.text("is_sample = 1"),
        postgresql_where=sa.text("is_sample"),
    )


def downgrade() -> None:
    op.drop_index("uq_sample_name", table_name="datasets")

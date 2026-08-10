"""drop memberships.is_active — a flag nothing ever cleared

It was read in eight places as an "active membership" filter, but no code path
ever set it False: removing someone from a department deletes the membership row.
Every one of those filters was permanently true, so the column described a
soft-delete that doesn't exist. Dropping it removes the trap of writing new code
against a guarantee the data never had.

The downgrade puts the column back as it was — non-null, defaulting to true,
which is what every surviving row held anyway, so nothing is lost by dropping it.

Revision ID: 0009_drop_membership_is_active
Revises: 0008_service_clients
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_drop_membership_is_active"
down_revision: Union[str, None] = "0008_service_clients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("memberships", "is_active")


def downgrade() -> None:
    op.add_column("memberships", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False))

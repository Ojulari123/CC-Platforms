"""users.is_platform_admin

Someone has to be able to create departments and administer across all of them
(see docs/decisions/2026-07-23-identity-structure.md). The per-department
"admin" role on Membership can't do that by definition — it's scoped to one
department.

Backfill: the earliest user becomes the first platform admin, so an existing
database isn't left with nobody able to create a department.

Revision ID: 0004_platform_admin
Revises: 0003_org_to_department
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_platform_admin"
down_revision: Union[str, None] = "0003_org_to_department"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET is_platform_admin = true WHERE id = (SELECT MIN(id) FROM users)")


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")

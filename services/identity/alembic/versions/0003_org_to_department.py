"""rename org -> department

CypherCrescent is the only organisation this platform will ever serve, so the
thing people actually pick when they join is their *department* (Engineering,
Data, ...). Teams sit inside a department.

Renames in place rather than drop/recreate so existing rows survive. Postgres
keeps index and constraint names when a table is renamed, so those are renamed
explicitly. Auto-generated FK names (teams_org_id_fkey etc.) are left alone —
cosmetic only, and renaming them buys nothing.

Revision ID: 0003_org_to_department
Revises: 0002_invites
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_org_to_department"
down_revision: Union[str, None] = "0002_invites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("orgs", "departments")
    op.execute("ALTER INDEX ix_orgs_slug RENAME TO ix_departments_slug")

    op.alter_column("teams", "org_id", new_column_name="dept_id")
    op.execute("ALTER TABLE teams RENAME CONSTRAINT uq_team_org_slug TO uq_team_dept_slug")

    op.alter_column("memberships", "org_id", new_column_name="dept_id")
    op.execute("ALTER TABLE memberships RENAME CONSTRAINT uq_membership_user_org TO uq_membership_user_dept")

    op.alter_column("invites", "org_id", new_column_name="dept_id")
    op.execute("ALTER INDEX ix_invites_org_id RENAME TO ix_invites_dept_id")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_invites_dept_id RENAME TO ix_invites_org_id")
    op.alter_column("invites", "dept_id", new_column_name="org_id")

    op.execute("ALTER TABLE memberships RENAME CONSTRAINT uq_membership_user_dept TO uq_membership_user_org")
    op.alter_column("memberships", "dept_id", new_column_name="org_id")

    op.execute("ALTER TABLE teams RENAME CONSTRAINT uq_team_dept_slug TO uq_team_org_slug")
    op.alter_column("teams", "dept_id", new_column_name="org_id")

    op.execute("ALTER INDEX ix_departments_slug RENAME TO ix_orgs_slug")
    op.rename_table("departments", "orgs")

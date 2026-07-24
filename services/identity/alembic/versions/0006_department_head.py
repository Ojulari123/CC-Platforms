"""departments.head_user_id — the named head of a department

Mirrors Team.manager_user_id. Before this, "who runs Engineering" could only be
answered as "whoever holds role=admin there", which is a set and can be empty or
several people. Pulse will need one name to escalate to, and an org chart needs
one name to draw.

Not the same as is_platform_admin, which is workspace-wide (IT/HR), and not the
same as the admin role, which stays a permission rather than a job title.

ON DELETE SET NULL: deleting a user must never delete the department.

Revision ID: 0006_department_head
Revises: 0005_team_manager
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_department_head"
down_revision: Union[str, None] = "0005_team_manager"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("departments", sa.Column("head_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_departments_head_user_id", "departments", "users",
        ["head_user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_departments_head_user_id", "departments", type_="foreignkey")
    op.drop_column("departments", "head_user_id")

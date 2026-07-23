"""teams.manager_user_id — the team's named lead

Until now a team's manager was inferred: whoever had role='manager' and
happened to be assigned to that team. Nothing enforced exactly one, so a team
could have none or several. Pulse routes each weekly report to the engineer's
team manager for approval, and that flow needs a single answer.

Nullable — a team can be between leads.

Revision ID: 0005_team_manager
Revises: 0004_platform_admin
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_team_manager"
down_revision: Union[str, None] = "0004_platform_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("manager_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_teams_manager_user_id", "teams", "users",
        ["manager_user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_teams_manager_user_id", "teams", type_="foreignkey")
    op.drop_column("teams", "manager_user_id")

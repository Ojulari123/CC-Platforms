"""repo-centric reporting: repos get a dept + lead + deputy; reports move onto repos

Session 05 restructure. Reporting is tied to the repository an engineer worked in,
not their team: `reports` gains `repo_id` and loses `team_id`, and the weekly
uniqueness becomes (author, repo, week). `repositories` gains dept/lead/deputy.
Still no cross-DB FKs into identity — dept_id/lead_user_id/deputy_user_id are ids.

See docs/decisions/2026-07-30-repo-centric-reporting.md.

Revision ID: 0003_repo_centric_reporting
Revises: 0002_github_activity
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_repo_centric_reporting"
down_revision: Union[str, None] = "0002_github_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # repositories: a repo now belongs to a department and has a lead + deputy.
    op.add_column("repositories", sa.Column("dept_id", sa.Integer(), nullable=True))
    op.add_column("repositories", sa.Column("lead_user_id", sa.Integer(), nullable=True))
    op.add_column("repositories", sa.Column("deputy_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_repositories_dept_id", "repositories", ["dept_id"])
    op.create_index("ix_repositories_lead_user_id", "repositories", ["lead_user_id"])
    op.create_index("ix_repositories_deputy_user_id", "repositories", ["deputy_user_id"])

    # reports: move off teams onto repos.
    op.drop_constraint("uq_report_author_week", "reports", type_="unique")
    op.add_column(
        "reports",
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_reports_repo_id", "reports", ["repo_id"])
    op.drop_index("ix_reports_team_id", table_name="reports")
    op.drop_column("reports", "team_id")
    op.alter_column("reports", "dept_id", existing_type=sa.Integer(), nullable=True)
    op.create_unique_constraint(
        "uq_report_author_repo_week", "reports", ["author_user_id", "repo_id", "week_start"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_report_author_repo_week", "reports", type_="unique")
    op.alter_column("reports", "dept_id", existing_type=sa.Integer(), nullable=False)
    op.add_column("reports", sa.Column("team_id", sa.Integer(), nullable=True))
    op.create_index("ix_reports_team_id", "reports", ["team_id"])
    op.drop_index("ix_reports_repo_id", table_name="reports")
    op.drop_column("reports", "repo_id")
    op.create_unique_constraint("uq_report_author_week", "reports", ["author_user_id", "week_start"])

    op.drop_index("ix_repositories_deputy_user_id", table_name="repositories")
    op.drop_index("ix_repositories_lead_user_id", table_name="repositories")
    op.drop_index("ix_repositories_dept_id", table_name="repositories")
    op.drop_column("repositories", "deputy_user_id")
    op.drop_column("repositories", "lead_user_id")
    op.drop_column("repositories", "dept_id")

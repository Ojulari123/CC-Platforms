"""who an open issue is queued to, and any date set for it

Next-week goals used to be written by asking the model for "a short, plausible set of
next steps implied by the in-progress work". That is a guess forward from commits, and
the report presented it as the person's plan. Goals now come from what somebody actually
stated: their journal entries for the repository, which `repo_journals` already holds,
and the open issues assigned to them, which the sync was not storing.

`issues.assignee_user_id` and `assignee_github_login` are the assignee, attributed the
same way an author is. They are separate columns rather than a reuse of the author
because the person who raised an issue is usually not the person who will do it, and it
is the second one whose plan the report describes.

`milestone_title` and `milestone_due_on` are the only parts of a milestone worth keeping:
a due date somebody set is the one deadline GitHub gives us, and a report that says when
work is due should be reading a real date rather than implying one.

Nullable with no backfill. GitHub sends all four on the issue payload and the sync never
read them, so nothing in this database can recover them. They fill in per issue as the
sync next sees it listed as updated, and an issue nobody touches again stays null, which
reads correctly as "not assigned to anyone we know of".

Revision ID: 0017_issue_assignee_milestone
Revises: 0016_pull_request_closed_at
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_issue_assignee_milestone"
down_revision: Union[str, None] = "0016_pull_request_closed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("assignee_user_id", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("assignee_github_login", sa.String(length=255), nullable=True))
    op.add_column("issues", sa.Column("milestone_title", sa.String(length=255), nullable=True))
    op.add_column("issues", sa.Column("milestone_due_on", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ix_issues_assignee_user_id", "issues", ["assignee_user_id"])


def downgrade() -> None:
    op.drop_index("ix_issues_assignee_user_id", table_name="issues")
    op.drop_column("issues", "milestone_due_on")
    op.drop_column("issues", "milestone_title")
    op.drop_column("issues", "assignee_github_login")
    op.drop_column("issues", "assignee_user_id")

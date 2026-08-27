"""whose money paid for a call

`GET /admin/llm-usage` was platform-admin only: the one person who is not spending
anybody's money but the platform's could see every figure, and the people actually
funding calls with their own or their department's key could see none of theirs. That
is the opposite of the rule the rest of the AI stack follows (llm_budget.may_see_figures
— figures belong to whoever pays).

Scoping the ledger needs a department on each row and there was nowhere to get one.
Pulse must not read identity's database, so it cannot ask which department a user_id
belongs to; the only departmental fact it can hold is the one written at spend time,
which is the department whose key paid. Null means a personal key or the platform's,
neither of which belongs on a department's invoice.

No backfill. Existing rows do not record which key funded them and the key that would
answer it may since have been rotated or deleted, so they stay null: they count towards
their own user's total and the platform total, and towards no department's.

Revision ID: 0018_llm_usage_dept_id
Revises: 0017_issue_assignee_milestone
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_llm_usage_dept_id"
down_revision: Union[str, None] = "0017_issue_assignee_milestone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("dept_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_llm_usage_dept_id"), "llm_usage", ["dept_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_usage_dept_id"), table_name="llm_usage")
    op.drop_column("llm_usage", "dept_id")

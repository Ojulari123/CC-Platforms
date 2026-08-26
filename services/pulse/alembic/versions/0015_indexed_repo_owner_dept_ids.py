"""records which departments the requester belonged to when an index was queued

A Celery task is handed an indexed_repos id and nothing else. Department membership
lives in identity and only a token carries it, so the worker could not see a department's
API key or its daily token allowance and quietly used the platform's instead. The effect
was that background indexing stopped earlier than interactive chat did for the same
person, which reads as a bug.

The alternative was asking identity for memberships at run time. That needs a new
internal endpoint, a new service scope, and that scope granted to Pulse's service client
row in every environment; and when identity is unreachable it degrades back to exactly
the behaviour being fixed, intermittently. Writing the ids at request time has no failure
mode and makes the job reproducible: it is evaluated against the permissions the
requester held when they asked.

Nullable with no backfill: an absent value means the same thing it means today, which is
that only the user's own key and allowance are reachable.

Revision ID: 0015_indexed_repo_owner_dept_ids
Revises: 0014_token_budgets
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_indexed_repo_owner_dept_ids"
down_revision: Union[str, None] = "0014_token_budgets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("indexed_repos", sa.Column("owner_dept_ids", sa.String(length=400), nullable=True))


def downgrade() -> None:
    op.drop_column("indexed_repos", "owner_dept_ids")

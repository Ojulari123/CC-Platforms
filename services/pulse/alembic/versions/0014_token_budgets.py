"""per-user and per-department daily token allowances

The daily cap was LLM_DAILY_TOKEN_CAP_PER_USER and nothing else, so only whoever deploys
the service could change it. This table makes it overridable at the same levels an API
key already is: a user row beats a department row beats a platform row beats the
environment variable.

Its own table rather than a column on api_credentials, because a person spending the
platform's key has no credential row and still has to be able to lower their own
allowance. No backfill: an absent row means "inherit", which is what every existing user
is doing today.

Revision ID: 0014_token_budgets
Revises: 0013_indexed_repo_ingest_sha
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_token_budgets"
down_revision: Union[str, None] = "0013_indexed_repo_ingest_sha"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("dept_id", sa.Integer(), nullable=True),
        sa.Column("daily_token_cap", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "owner_user_id", "dept_id", name="uq_token_budget_scope"),
    )
    op.create_index(op.f("ix_token_budgets_owner_user_id"), "token_budgets", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_token_budgets_dept_id"), "token_budgets", ["dept_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_token_budgets_dept_id"), table_name="token_budgets")
    op.drop_index(op.f("ix_token_budgets_owner_user_id"), table_name="token_budgets")
    op.drop_table("token_budgets")

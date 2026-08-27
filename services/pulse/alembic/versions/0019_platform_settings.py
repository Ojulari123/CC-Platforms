"""platform-wide switches a platform admin can change without a redeploy

The first one is whether a department admin may read their department's token figures
while the platform's key is paying. Today llm_budget.may_see_figures says no, because
the figures belong to whoever pays and that is the platform. That stays the default;
this table only makes it a decision instead of a fixed behaviour.

There was nowhere for a platform-wide fact to live. token_budgets and api_credentials
are both keyed by (scope, owner_user_id, dept_id) and token_budgets' platform row
carries one integer cap, so a boolean would have to arrive as a nullable column that
means nothing on the rows beside it. An environment variable was ruled out: changing it
needs a redeploy, and this is a decision an admin makes in the product.

Key/value rather than a column per switch, so the next one costs a constant instead of
a migration. Absence of a row means the default, which is why there is no seed insert.

Revision ID: 0019_platform_settings
Revises: 0018_llm_usage_dept_id
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_platform_settings"
down_revision: Union[str, None] = "0018_llm_usage_dept_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_settings_key"), "platform_settings", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_settings_key"), table_name="platform_settings")
    op.drop_table("platform_settings")

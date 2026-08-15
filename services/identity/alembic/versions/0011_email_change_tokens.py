"""email_change_tokens — verify-then-swap for the sign-in address

Same shape as password_reset_tokens: the raw token only exists in the link emailed to
the NEW address, the DB keeps its SHA-256 hash, single-use and short-lived
(EMAIL_CHANGE_EXPIRE_MINUTES). The pending address is parked here rather than on
users, so nothing about the account moves until the new mailbox answers.
user_token_version pins the link to the account state it was issued under, so changing
the password or signing out everywhere cancels a link already sitting in an inbox.

Revision ID: 0011_email_change_tokens
Revises: 0010_user_onboarded_at
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_email_change_tokens"
down_revision: Union[str, None] = "0010_user_onboarded_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_change_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("new_email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_change_tokens_user_id", "email_change_tokens", ["user_id"])
    op.create_index("ix_email_change_tokens_token_hash", "email_change_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_email_change_tokens_token_hash", table_name="email_change_tokens")
    op.drop_index("ix_email_change_tokens_user_id", table_name="email_change_tokens")
    op.drop_table("email_change_tokens")

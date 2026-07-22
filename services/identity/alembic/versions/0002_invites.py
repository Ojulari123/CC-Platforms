"""invites: one-time org invitations

Revision ID: 0002_invites
Revises: 0001_initial
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_invites"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invites_org_id", "invites", ["org_id"])
    op.create_index("ix_invites_email", "invites", ["email"])
    op.create_index("ix_invites_token_hash", "invites", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invites_token_hash", table_name="invites")
    op.drop_index("ix_invites_email", table_name="invites")
    op.drop_index("ix_invites_org_id", table_name="invites")
    op.drop_table("invites")

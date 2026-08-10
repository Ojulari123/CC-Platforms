"""users.onboarded_at — an explicit record that an account was onboarded

Replaces the delete guard's old token_version > 0 check, which fired on any password
change. The backfill is deliberately wider than "has a membership": an ex-member's row
was deleted on the way out, so it stamps everyone the old rule would have refused, and
nobody undeletable before this migration is deletable after it. Rationale in
services/identity/README.md, "Why users.onboarded_at exists".

Revision ID: 0010_user_onboarded_at
Revises: 0009_drop_membership_is_active
Create Date: 2026-08-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_user_onboarded_at"
down_revision: Union[str, None] = "0009_drop_membership_is_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKFILL = """
UPDATE users SET onboarded_at = COALESCE(
    (SELECT MIN(m.created_at) FROM memberships m WHERE m.user_id = users.id),
    users.created_at
)
WHERE onboarded_at IS NULL AND (
    EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id)
    OR users.token_version > 0
    OR users.email_verified
    OR EXISTS (SELECT 1 FROM invites i WHERE i.email = users.email AND i.accepted_at IS NOT NULL)
)
"""


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarded_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_column("users", "onboarded_at")

"""when a pull request stopped being open

`pull_requests` held merged_at and nothing else, so a pull request that was closed
without being merged carried no closure date at all. Report payloads sent `closed_at`
as a hardcoded null to stop the model reading `state: "closed"` plus the one date it
had (the open date) as the closure. That kept the model honest but told it nothing:
"this was closed, we will not say when".

The live report path already had GitHub's closed_at in hand and passed it through, so
the same report worded a closure differently depending on whether the repository was
synced. This column is what makes the two paths agree.

No backfill is possible. GitHub sends closed_at on the pull request payload and the
sync never stored it, so for existing rows the value is not merely unknown to us, it
is nowhere in this database to recover. They stay null until a sync touches the pull
request again, which happens the next time GitHub lists it as updated.

Revision ID: 0016_pull_request_closed_at
Revises: 0015_indexed_repo_owner_dept_ids
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_pull_request_closed_at"
down_revision: Union[str, None] = "0015_indexed_repo_owner_dept_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pull_requests", sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("pull_requests", "closed_at")

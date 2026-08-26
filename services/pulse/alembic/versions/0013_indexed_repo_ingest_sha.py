"""checkpoint column so a failed ingest can resume

`indexed_repos.ingest_sha` records which commit a run is part way through. Chunks are
now written in batches rather than all at once at the end, so a run that fails after two
thousand files has two thousand files' worth of rows already stored; this column is what
tells a retry that those rows belong to the commit it is about to index and can be kept.
It is cleared on success, and a value that does not match the current HEAD makes the next
run start clean.

Nullable with no backfill: every existing row finished (or failed) under the old
all-at-once write, so none of them has a partial ingest to resume.

Revision ID: 0013_indexed_repo_ingest_sha
Revises: 0012_report_persona
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_indexed_repo_ingest_sha"
down_revision: Union[str, None] = "0012_report_persona"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("indexed_repos", sa.Column("ingest_sha", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("indexed_repos", "ingest_sha")

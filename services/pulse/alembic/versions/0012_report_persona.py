"""records which persona wrote a report

`reports.persona_id` is deliberately NOT a foreign key. A persona is a tone a user can
delete at any time, and a report is a record of work that has to outlive it — a real FK
with a cascade would delete reports, and one with SET NULL would erase the only trace of
how a report was written. So the column is a plain indexed integer that may point at a
persona that no longer exists, the same treatment cross-service ids get everywhere else
in this service.

Revision ID: 0012_report_persona
Revises: 0011_personas_and_credentials
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_report_persona"
down_revision: Union[str, None] = "0011_personas_and_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("persona_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_reports_persona_id"), "reports", ["persona_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reports_persona_id"), table_name="reports")
    op.drop_column("reports", "persona_id")

"""split who wrote a report from who it is about

`reports.author_user_id` has meant both "who wrote this" and "who this is about" since
the table was created, because on a weekly report they are the same person. Reporting on
someone else's work breaks that, so the subject moves into its own column, and a report
that covers several contributors gets a `report_subjects` row per person — each with its
own attributed section rather than one blended narrative.

Two columns lose their NOT NULL: `repo_id` (an ad-hoc report may target a repository
Pulse does not track — `repo_full_name` carries it instead) and `week_start` (an ad-hoc
report has a range, not a calendar week). That guts
`uq_report_author_repo_week`: NULLs never collide, so the constraint would stop guarding
anything an ad-hoc row could violate while still applying to rows it should not. It is
replaced by a partial unique index over the same three columns, restricted to
`kind = 'weekly'`. The matching Index is declared on the model too, or autogenerate
reads the real index as drift.

Existing rows are all weekly reports about their own author, so the backfill sets
subject_user_id = author_user_id, range_start/range_end to the Monday..Sunday of
week_start, and copies repositories.full_name onto repo_full_name. `kind` comes from
its server default.

DOWNGRADE DELETES DATA: restoring NOT NULL on repo_id and week_start is impossible while
an ad-hoc report exists, so downgrade() first deletes every report that is not weekly or
is missing a repo/week. Their approvals, comments and subjects go with them by cascade.

Revision ID: 0010_report_subjects
Revises: 0009_chat_conversations
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_report_subjects"
down_revision: Union[str, None] = "0009_chat_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("subject_user_id", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("subject_github_login", sa.String(255), nullable=True))
    op.add_column("reports", sa.Column("repo_full_name", sa.String(400), nullable=True))
    op.add_column("reports", sa.Column("range_start", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("range_end", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("kind", sa.String(30), server_default="weekly", nullable=False))
    op.create_index("ix_reports_subject_user_id", "reports", ["subject_user_id"])
    op.create_index("ix_reports_repo_full_name", "reports", ["repo_full_name"])

    op.execute("UPDATE reports SET subject_user_id = author_user_id WHERE subject_user_id IS NULL")
    op.execute(
        "UPDATE reports SET range_start = week_start, "
        "range_end = (week_start + INTERVAL '6 days')::date "
        "WHERE range_start IS NULL AND week_start IS NOT NULL"
    )
    op.execute(
        "UPDATE reports r SET repo_full_name = repo.full_name "
        "FROM repositories repo WHERE repo.id = r.repo_id AND r.repo_full_name IS NULL"
    )

    op.alter_column("reports", "repo_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("reports", "week_start", existing_type=sa.Date(), nullable=True)

    op.drop_constraint("uq_report_author_repo_week", "reports", type_="unique")
    op.create_index(
        "uq_report_author_repo_week",
        "reports",
        ["author_user_id", "repo_id", "week_start"],
        unique=True,
        postgresql_where=sa.text("kind = 'weekly'"),
    )

    op.create_table(
        "report_subjects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("subject_user_id", sa.Integer(), nullable=True),
        sa.Column("subject_github_login", sa.String(255), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_subjects_report_id", "report_subjects", ["report_id"])
    op.create_index("ix_report_subjects_subject_user_id", "report_subjects", ["subject_user_id"])


def downgrade() -> None:
    op.drop_index("ix_report_subjects_subject_user_id", table_name="report_subjects")
    op.drop_index("ix_report_subjects_report_id", table_name="report_subjects")
    op.drop_table("report_subjects")

    # See the DOWNGRADE DELETES DATA note above: NOT NULL cannot be restored around
    # them, and there is nowhere in the old schema to put them.
    op.execute("DELETE FROM reports WHERE kind <> 'weekly' OR repo_id IS NULL OR week_start IS NULL")

    op.drop_index("uq_report_author_repo_week", table_name="reports")
    op.alter_column("reports", "week_start", existing_type=sa.Date(), nullable=False)
    op.alter_column("reports", "repo_id", existing_type=sa.Integer(), nullable=False)
    op.create_unique_constraint("uq_report_author_repo_week", "reports", ["author_user_id", "repo_id", "week_start"])

    op.drop_index("ix_reports_repo_full_name", table_name="reports")
    op.drop_index("ix_reports_subject_user_id", table_name="reports")
    op.drop_column("reports", "kind")
    op.drop_column("reports", "range_end")
    op.drop_column("reports", "range_start")
    op.drop_column("reports", "repo_full_name")
    op.drop_column("reports", "subject_github_login")
    op.drop_column("reports", "subject_user_id")

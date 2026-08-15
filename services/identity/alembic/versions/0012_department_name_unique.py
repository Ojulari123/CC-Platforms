"""departments.name unique, case-insensitively

Only the slug was unique before, so "Software Dev" could be created three times and be
told apart only by software-dev-2 / -3. The index folds case, because "Software Dev"
and "software dev" are the same department to anyone reading the list.

The index is lower(name), not lower(trim(name)): Postgres stores the latter as
TRIM(BOTH FROM name), which never matches what SQLAlchemy renders for the model, and
alembic's autogenerate then reports drift on every run forever. Surrounding whitespace
is stripped by the request schemas instead, so " Data " cannot be created alongside
"Data". The guard below is deliberately stricter than the index — it groups on
lower(trim(name)) — so a padded near-duplicate already in the table is caught here
rather than surviving into a constrained world where nobody can create its twin.

This migration does NOT touch data. Existing duplicates are consolidated first, through
the API, by scripts/merge-duplicate-departments.py — going through the service layer is
what keeps the last-admin, leadership-handover and non-empty-department rules applying.
If duplicates are still present the migration stops and names them rather than renaming
or deleting anything behind the operator's back.

Revision ID: 0012_department_name_unique
Revises: 0011_email_change_tokens
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_department_name_unique"
down_revision: Union[str, None] = "0011_email_change_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DUPLICATES = """
SELECT lower(trim(name)) AS key, count(*) AS n
FROM departments GROUP BY lower(trim(name)) HAVING count(*) > 1 ORDER BY 1
"""


def duplicate_department_names(bind) -> list[tuple[str, int]]:
    return [(key, n) for key, n in bind.execute(sa.text(_DUPLICATES)).all()]


def upgrade() -> None:
    duplicates = duplicate_department_names(op.get_bind())
    if duplicates:
        listed = ", ".join(f"{key!r} x{n}" for key, n in duplicates)
        raise RuntimeError(
            f"Cannot add the unique department name index: {len(duplicates)} name(s) are still "
            f"duplicated ({listed}). Consolidate them first — python scripts/merge-duplicate-departments.py "
            "--identity-url http://localhost:8001 --email <platform admin> --apply — then run this migration again."
        )
    op.create_index("uq_departments_name_lower", "departments", [sa.text("lower(name)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_departments_name_lower", table_name="departments")

"""personas and bring-your-own API keys

Two tables that both exist so a customer can decide how AI behaves and who pays for it.

`personas` is a reusable tone: four independent dials (length, audience, technical depth,
formality) plus freeform guidance, rather than one opaque preset string — the useful
combinations are ones nobody would have thought to name. A row with `owner_user_id`
NULL is a system preset: visible to everyone, editable by no one. Three are seeded here
(Concise, Executive, Technical Depth) and Concise is what the resolver falls back to
when a user has picked nothing. The values are written out as literal SQL rather than
imported from app.models, because a migration has to keep meaning what it meant on the
day it ran; models.PERSONA_SYSTEM_PRESETS holds the same values for the running app.

`api_credentials` holds a customer's own LLM key. The key is Fernet-encrypted with the
same mechanism already protecting GitHub tokens, and only `last_four` is ever readable,
so the column is deliberately not a place a leaked database hands over usable keys.
`bypass_token_cap` sits on the row and not in configuration because it may only ever
lift a cap on spend the row's owner is paying for — the platform's env key has no row
here and is never bypassable.

DOWNGRADE DELETES DATA: dropping `api_credentials` destroys every stored key, and there
is nowhere else they exist. Anyone who installed one has to install it again.

Revision ID: 0011_personas_and_credentials
Revises: 0010_report_subjects
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_personas_and_credentials"
down_revision: Union[str, None] = "0010_report_subjects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SYSTEM_PERSONAS = (
    (
        "Concise",
        "brief",
        "manager",
        "medium",
        "neutral",
        "Lead with what shipped. Cut throat-clearing and restating the question.",
    ),
    (
        "Executive",
        "brief",
        "executive",
        "low",
        "formal",
        "Outcomes and risk, not mechanics. No PR numbers, no tool names.",
    ),
    (
        "Technical Depth",
        "detailed",
        "engineer",
        "high",
        "neutral",
        "Name the components, the approach taken and anything still unresolved.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("length", sa.String(30), nullable=False),
        sa.Column("audience", sa.String(30), nullable=False),
        sa.Column("technical_depth", sa.String(30), nullable=False),
        sa.Column("formality", sa.String(30), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_persona_owner_name"),
    )
    op.create_index("ix_personas_owner_user_id", "personas", ["owner_user_id"])

    personas = sa.table(
        "personas",
        sa.column("owner_user_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("length", sa.String),
        sa.column("audience", sa.String),
        sa.column("technical_depth", sa.String),
        sa.column("formality", sa.String),
        sa.column("instructions", sa.Text),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        personas,
        [
            {
                "owner_user_id": None,
                "name": name,
                "length": length,
                "audience": audience,
                "technical_depth": technical_depth,
                "formality": formality,
                "instructions": instructions,
                "is_default": False,
            }
            for name, length, audience, technical_depth, formality, instructions in _SYSTEM_PERSONAS
        ],
    )

    op.create_table(
        "api_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("dept_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("key_encrypted", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("last_four", sa.String(8), nullable=False),
        sa.Column("bypass_token_cap", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "owner_user_id", "dept_id", "provider", name="uq_api_credential_scope_provider"),
    )
    op.create_index("ix_api_credentials_owner_user_id", "api_credentials", ["owner_user_id"])
    op.create_index("ix_api_credentials_dept_id", "api_credentials", ["dept_id"])


def downgrade() -> None:
    op.drop_index("ix_api_credentials_dept_id", table_name="api_credentials")
    op.drop_index("ix_api_credentials_owner_user_id", table_name="api_credentials")
    op.drop_table("api_credentials")

    op.drop_index("ix_personas_owner_user_id", table_name="personas")
    op.drop_table("personas")

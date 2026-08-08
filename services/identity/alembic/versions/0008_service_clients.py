"""service_clients — OAuth2 client-credentials for service-to-service auth

A non-human caller (Pulse) authenticates as itself and gets a scoped service
token. The secret is stored bcrypt-hashed (same as a user password); is_active
makes a client revocable without deleting the row.

Revision ID: 0008_service_clients
Revises: 0007_password_reset
Create Date: 2026-08-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_service_clients"
down_revision: Union[str, None] = "0007_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("client_secret_hash", sa.String(255), nullable=False),
        sa.Column("scopes", sa.String(500), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_service_clients_client_id", "service_clients", ["client_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_service_clients_client_id", table_name="service_clients")
    op.drop_table("service_clients")

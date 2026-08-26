"""chat conversations, messages and the citations behind each answer

An answer that cites nothing is an assertion, so every assistant message keeps the
chunks it was grounded in as rows of its own.

The one unusual choice is chat_citations.indexed_repo_id: nullable, with ondelete
SET NULL, next to a denormalised copy of full_name and path. Everything else in this
schema cascades from its parent, but an index is a cache of a repository that gets
deleted and rebuilt, and cascading from it would silently delete the evidence under
answers people have already read. SET NULL leaves the citation readable — repo, file,
lines and snippet — and only loses the link back into Pulse's copy of the index.

Revision ID: 0009_chat_conversations
Revises: 0008_repo_index
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_chat_conversations"
down_revision: Union[str, None] = "0008_repo_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])

    op.create_table(
        "chat_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("indexed_repo_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(400), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["indexed_repo_id"], ["indexed_repos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_citations_message_id", "chat_citations", ["message_id"])
    op.create_index("ix_chat_citations_indexed_repo_id", "chat_citations", ["indexed_repo_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_citations_indexed_repo_id", table_name="chat_citations")
    op.drop_index("ix_chat_citations_message_id", table_name="chat_citations")
    op.drop_table("chat_citations")

    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_conversations_user_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")

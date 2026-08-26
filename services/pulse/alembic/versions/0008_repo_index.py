"""repository content index: ingested repos and their embedded chunks

The chat assistant answers from a repository's actual files, so the files have to be
stored somewhere it can search by meaning rather than by keyword. That is what the
`vector` extension buys: `repo_chunks.embedding` holds one point per chunk and Postgres
orders by cosine distance. `indexed_repos.repo_id` is nullable because a public repo can
be indexed on request without Pulse ever tracking it — such a row has no `repositories`
parent, only a full_name.

Know what the HNSW index below does and does not do. Measured on PG16 / pgvector 0.8
with 3000 chunks: an unfiltered `ORDER BY embedding <=> $1 LIMIT k` does use it, but
retrieval always filters to one repository, and with `WHERE indexed_repo_id = $1` the
planner prefers the btree on that column plus a top-N sort — an exact scan of that one
repo's chunks, not an approximate index scan. That is correct and, at a few thousand
chunks, fast (27 ms measured); it is linear in the size of a single repository. If one
repo's chunk count ever makes that too slow, the fix is a per-repo partial HNSW index or
a two-step query, not a change to this one.

The HNSW index is built here at zero rows, which costs nothing. Rebuilding one over a
populated table is the expensive case, and it wants a large maintenance_work_mem —
that has to be set on a DIRECT connection. Neon's pooled endpoint (`-pooler` in the
host) is PgBouncer in transaction mode and cannot run SET at all, so a future rebuild
must use the direct host. See DEPLOY.md.

Revision ID: 0008_repo_index
Revises: 0007_repo_journals
Create Date: 2026-08-25

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0008_repo_index"
down_revision: Union[str, None] = "0007_repo_journals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matches models.EMBEDDING_DIM (text-embedding-3-small). A vector column's width is
# fixed by the DDL that creates it, so changing models needs a new migration.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    # Before the vector column, not after: the column type does not exist until this
    # runs. Neon ships pgvector on every plan and its role may create it; local dev
    # gets it from the pgvector/pgvector:pg16 image in docker-compose.yml.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "indexed_repos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(400), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "full_name", name="uq_indexed_repo_owner_full_name"),
    )
    op.create_index("ix_indexed_repos_repo_id", "indexed_repos", ["repo_id"])
    op.create_index("ix_indexed_repos_full_name", "indexed_repos", ["full_name"])
    op.create_index("ix_indexed_repos_owner_user_id", "indexed_repos", ["owner_user_id"])

    op.create_table(
        "repo_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("indexed_repo_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["indexed_repo_id"], ["indexed_repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_chunks_indexed_repo_id", "repo_chunks", ["indexed_repo_id"])

    # Cosine, matching how retrieval orders: an HNSW index built for one distance
    # operator is not used by a query written in another, and the query silently falls
    # back to a sequential scan instead of erroring.  Built at zero rows, where it is
    # free; see the note above about when the planner actually reaches for it.
    op.create_index(
        "ix_repo_chunks_embedding_hnsw",
        "repo_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    # The `vector` extension is deliberately NOT dropped. CREATE EXTENSION is
    # database-wide, so dropping it here would take out any other table that has since
    # come to hold a vector column, in a migration that only owns these two tables.
    # Removing it is an operator's decision, not this revision's.
    op.drop_index("ix_repo_chunks_embedding_hnsw", table_name="repo_chunks")
    op.drop_index("ix_repo_chunks_indexed_repo_id", table_name="repo_chunks")
    op.drop_table("repo_chunks")

    op.drop_index("ix_indexed_repos_owner_user_id", table_name="indexed_repos")
    op.drop_index("ix_indexed_repos_full_name", table_name="indexed_repos")
    op.drop_index("ix_indexed_repos_repo_id", table_name="indexed_repos")
    op.drop_table("indexed_repos")

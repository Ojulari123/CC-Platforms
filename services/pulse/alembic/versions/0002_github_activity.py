"""github integration: accounts, repositories, commits, pull_requests, reviews, issues, sync_runs

The Week-3 GitHub sync domain. Still no foreign keys into identity — people and
teams are referenced by id only (CLAUDE.md rule 3). GitHub's own numeric ids are
stored as BigInteger and kept unique so a re-sync updates rather than duplicates.

Revision ID: 0002_github_activity
Revises: 0001_initial
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_github_activity"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(255), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(500), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_github_accounts_user_id", "github_accounts", ["user_id"], unique=True)
    op.create_index("ix_github_accounts_github_user_id", "github_accounts", ["github_user_id"], unique=True)
    op.create_index("ix_github_accounts_github_login", "github_accounts", ["github_login"])

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(400), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_branch", sa.String(255), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_repositories_github_repo_id", "repositories", ["github_repo_id"], unique=True)
    op.create_index("ix_repositories_full_name", "repositories", ["full_name"])

    op.create_table(
        "commits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha", sa.String(40), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_github_login", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("additions", sa.Integer(), nullable=True),
        sa.Column("deletions", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id", "sha", name="uq_commit_repo_sha"),
    )
    op.create_index("ix_commits_repo_id", "commits", ["repo_id"])
    op.create_index("ix_commits_author_user_id", "commits", ["author_user_id"])
    op.create_index("ix_commits_committed_at", "commits", ["committed_at"])

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_pr_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("merged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_github_login", sa.String(255), nullable=True),
        sa.Column("gh_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gh_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id", "number", name="uq_pr_repo_number"),
    )
    op.create_index("ix_pull_requests_repo_id", "pull_requests", ["repo_id"])
    op.create_index("ix_pull_requests_github_pr_id", "pull_requests", ["github_pr_id"], unique=True)
    op.create_index("ix_pull_requests_author_user_id", "pull_requests", ["author_user_id"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_review_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_github_login", sa.String(255), nullable=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reviews_pull_request_id", "reviews", ["pull_request_id"])
    op.create_index("ix_reviews_github_review_id", "reviews", ["github_review_id"], unique=True)
    op.create_index("ix_reviews_reviewer_user_id", "reviews", ["reviewer_user_id"])

    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_github_login", sa.String(255), nullable=True),
        sa.Column("gh_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id", "number", name="uq_issue_repo_number"),
    )
    op.create_index("ix_issues_repo_id", "issues", ["repo_id"])
    op.create_index("ix_issues_github_issue_id", "issues", ["github_issue_id"], unique=True)
    op.create_index("ix_issues_author_user_id", "issues", ["author_user_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sync_runs_repo_id", "sync_runs", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_repo_id", table_name="sync_runs")
    op.drop_table("sync_runs")

    op.drop_index("ix_issues_author_user_id", table_name="issues")
    op.drop_index("ix_issues_github_issue_id", table_name="issues")
    op.drop_index("ix_issues_repo_id", table_name="issues")
    op.drop_table("issues")

    op.drop_index("ix_reviews_reviewer_user_id", table_name="reviews")
    op.drop_index("ix_reviews_github_review_id", table_name="reviews")
    op.drop_index("ix_reviews_pull_request_id", table_name="reviews")
    op.drop_table("reviews")

    op.drop_index("ix_pull_requests_author_user_id", table_name="pull_requests")
    op.drop_index("ix_pull_requests_github_pr_id", table_name="pull_requests")
    op.drop_index("ix_pull_requests_repo_id", table_name="pull_requests")
    op.drop_table("pull_requests")

    op.drop_index("ix_commits_committed_at", table_name="commits")
    op.drop_index("ix_commits_author_user_id", table_name="commits")
    op.drop_index("ix_commits_repo_id", table_name="commits")
    op.drop_table("commits")

    op.drop_index("ix_repositories_full_name", table_name="repositories")
    op.drop_index("ix_repositories_github_repo_id", table_name="repositories")
    op.drop_table("repositories")

    op.drop_index("ix_github_accounts_github_login", table_name="github_accounts")
    op.drop_index("ix_github_accounts_github_user_id", table_name="github_accounts")
    op.drop_index("ix_github_accounts_user_id", table_name="github_accounts")
    op.drop_table("github_accounts")

from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Integer, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.db import Base

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CHANGES_REQUESTED = "changes_requested"
ACTION_SUBMITTED = "submitted"
ACTION_APPROVED = "approved"
ACTION_REJECTED = "rejected"
ACTION_CHANGES_REQUESTED = "changes_requested"

class Report(Base):
    """One engineer's weekly report, about a repo. Pulse never stores names/emails, and never reads identity's
    database. The AI-drafted summary fields are plain editable text for now; the generation step is Week 4"""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    author_user_id = Column(Integer, nullable=False, index=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    dept_id = Column(Integer, nullable=True, index=True)
    week_start = Column(Date, nullable=False)
    status = Column(String(30), nullable=False, server_default=STATUS_DRAFT, default=STATUS_DRAFT)
    summary_manager = Column(Text, nullable=True)
    summary_exec = Column(Text, nullable=True)
    next_week_goals = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="reports")
    approvals = relationship("Approval", back_populates="report", cascade="all, delete-orphan", order_by="Approval.created_at")
    comments = relationship("Comment", back_populates="report", cascade="all, delete-orphan", order_by="Comment.created_at")

    __table_args__ = (UniqueConstraint("author_user_id", "repo_id", "week_start", name="uq_report_author_repo_week"),)

class Approval(Base):
    """Append-only history of what happened to a report. Who did what, when, and why. 
    
    Rows are never updated or deleted; Report.status is the denormalised
    'current state' derived from the latest entry, kept for fast listing"""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    report = relationship("Report", back_populates="approvals")

class Comment(Base):
    """A flat comment on a report. Authored by a user referenced by id"""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(TIMESTAMP(timezone=True), nullable=True)

    report = relationship("Report", back_populates="comments")

class GitHubAccount(Base):
    """Links an identity user to their GitHub identity, and stores the OAuth access
    token — encrypted at rest, never plaintext, never logged. One per user."""
    __tablename__ = "github_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)  # identity user id
    github_user_id = Column(BigInteger, unique=True, index=True, nullable=False)
    github_login = Column(String(255), index=True, nullable=False)
    access_token_encrypted = Column(Text, nullable=False)
    scopes = Column(String(500), nullable=True)
    connected_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class Repository(Base):
    """A GitHub repo we track. We make use of an org/allowlist, so repos
    are seeded from config, not per-user. is_tracked toggles a repo off without
    losing its history; last_synced_at is the cursor for incremental pulls."""
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    github_repo_id = Column(BigInteger, unique=True, index=True, nullable=False)
    full_name = Column(String(400), index=True, nullable=False)  # owner/name
    owner = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    private = Column(Boolean, nullable=False, server_default="false", default=False)
    is_tracked = Column(Boolean, nullable=False, server_default="true", default=True)
    default_branch = Column(String(255), nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    dept_id = Column(Integer, index=True, nullable=True)
    lead_user_id = Column(Integer, index=True, nullable=True)
    deputy_user_id = Column(Integer, index=True, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    commits = relationship("Commit", back_populates="repository", cascade="all, delete-orphan")
    pull_requests = relationship("PullRequest", back_populates="repository", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="repository", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="repository", cascade="all, delete-orphan")

class Commit(Base):
    """A commit on a tracked repo. Attributed to an engineer (author_user_id) when
    the commit's GitHub login matches a connected account; otherwise just the login."""
    __tablename__ = "commits"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    sha = Column(String(40), nullable=False)
    author_user_id = Column(Integer, index=True, nullable=True)
    author_github_login = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    url = Column(String(500), nullable=True)
    committed_at = Column(TIMESTAMP(timezone=True), index=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="commits")

    __table_args__ = (UniqueConstraint("repo_id", "sha", name="uq_commit_repo_sha"),)

class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    github_pr_id = Column(BigInteger, unique=True, index=True, nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    state = Column(String(20), nullable=False)  # open | closed
    merged = Column(Boolean, nullable=False, server_default="false", default=False)
    author_user_id = Column(Integer, index=True, nullable=True)
    author_github_login = Column(String(255), nullable=True)
    gh_created_at = Column(TIMESTAMP(timezone=True), nullable=True)
    gh_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    merged_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="pull_requests")
    reviews = relationship("Review", back_populates="pull_request", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_pr_repo_number"),)

class Review(Base):
    """A review left on a pull request (approved / changes requested / commented)"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True, nullable=False)
    github_review_id = Column(BigInteger, unique=True, index=True, nullable=False)
    reviewer_user_id = Column(Integer, index=True, nullable=True)
    reviewer_github_login = Column(String(255), nullable=True)
    state = Column(String(30), nullable=False)  # approved | changes_requested | commented | dismissed
    submitted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    pull_request = relationship("PullRequest", back_populates="reviews")

class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    github_issue_id = Column(BigInteger, unique=True, index=True, nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    state = Column(String(20), nullable=False)  # open | closed
    author_user_id = Column(Integer, index=True, nullable=True)
    author_github_login = Column(String(255), nullable=True)
    gh_created_at = Column(TIMESTAMP(timezone=True), nullable=True)
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="issues")

    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_issue_repo_number"),)

class SyncRun(Base):
    """Audit log of sync jobs. When we pulled, for which repo, and how it went.
    
    Makes 'why is the data stale?' answerable and gives the scheduled job a trail."""
    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=True)
    status = Column(String(20), nullable=False)  # running | success | error
    detail = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)

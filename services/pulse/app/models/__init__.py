from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Index, Integer, LargeBinary, String, Text, text, TIMESTAMP, UniqueConstraint, func
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
REPORT_KIND_WEEKLY = "weekly"
REPORT_KIND_ADHOC = "adhoc"
LLM_KIND_REPORT = "report"
LLM_KIND_JOURNAL_ROLLUP = "journal_rollup"
LLM_KIND_EMBEDDING = "embedding"
LLM_KIND_CHAT = "chat"
INDEX_PENDING = "pending"
INDEX_RUNNING = "running"
INDEX_READY = "ready"
INDEX_ERROR = "error"
INDEX_RATE_LIMITED = "rate_limited"
# Stopped on purpose with its work intact, not broken. Everything already embedded is
# stored and `ingest_sha` still points at the commit it belongs to, so the next run
# carries on. Searchable only means INDEX_READY, so a paused index answers nothing.
INDEX_PAUSED = "paused"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

# A persona is four independent dials plus freeform guidance, not one opaque preset
# string: "brief and technical for an engineer" is a combination nobody would have
# thought to name, and a fixed list of named presets cannot express it.
PERSONA_LENGTHS = ("brief", "standard", "detailed")
PERSONA_AUDIENCES = ("executive", "manager", "engineer")
PERSONA_TECHNICAL_DEPTHS = ("low", "medium", "high")
PERSONA_FORMALITIES = ("casual", "neutral", "formal")

# The starter the resolver falls back to when a user has picked nothing.
DEFAULT_SYSTEM_PERSONA = "Concise"

# Seeded with owner_user_id = NULL by migration 0011 and read-only to everyone. The
# migration writes these values as literal SQL rather than importing this tuple, because
# a migration has to keep meaning what it meant on the day it was written; change one
# here and the seed there needs the same change.
PERSONA_SYSTEM_PRESETS = (
    {
        "name": DEFAULT_SYSTEM_PERSONA,
        "length": "brief",
        "audience": "manager",
        "technical_depth": "medium",
        "formality": "neutral",
        "instructions": "Lead with what shipped. Cut throat-clearing and restating the question.",
    },
    {
        "name": "Executive",
        "length": "brief",
        "audience": "executive",
        "technical_depth": "low",
        "formality": "formal",
        "instructions": "Outcomes and risk, not mechanics. No PR numbers, no tool names.",
    },
    {
        "name": "Technical Depth",
        "length": "detailed",
        "audience": "engineer",
        "technical_depth": "high",
        "formality": "neutral",
        "instructions": "Name the components, the approach taken and anything still unresolved.",
    },
)

SCOPE_USER = "user"
SCOPE_DEPARTMENT = "department"
# Only token_budgets uses this scope. There is no platform API credential row: the
# platform's key is an environment variable, and nothing about it is per-tenant. A
# platform token budget IS a row, because a platform admin has to be able to change the
# default without a redeploy.
SCOPE_PLATFORM = "platform"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

# Width of text-embedding-3-small, the model in settings.EMBEDDING_MODEL. Hardcoded
# rather than read from config: a vector column's width is fixed by the DDL that
# created it, so a config change could never resize an existing column anyway — it
# would only make the model disagree with the database. config.EMBEDDING_DIMENSIONS
# is checked against this at startup instead.
EMBEDDING_DIM = 1536

class Report(Base):
    """author_user_id is who wrote the report; subject_user_id is who it is about. On a
    weekly report they are the same person, which is the assumption an ad-hoc report on
    someone else's work breaks — hence two columns rather than one.

    repo_id and week_start are nullable because an ad-hoc report can target a repository
    Pulse does not track (repo_full_name only) over an arbitrary range (range_start /
    range_end) rather than a calendar week."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    author_user_id = Column(Integer, nullable=False, index=True)
    subject_user_id = Column(Integer, nullable=True, index=True)
    subject_github_login = Column(String(255), nullable=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True)
    repo_full_name = Column(String(400), nullable=True, index=True)
    dept_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(30), nullable=False, server_default=REPORT_KIND_WEEKLY, default=REPORT_KIND_WEEKLY)
    week_start = Column(Date, nullable=True)
    range_start = Column(Date, nullable=True)
    range_end = Column(Date, nullable=True)
    status = Column(String(30), nullable=False, server_default=STATUS_DRAFT, default=STATUS_DRAFT)
    summary_manager = Column(Text, nullable=True)
    summary_exec = Column(Text, nullable=True)
    next_week_goals = Column(Text, nullable=True)
    generated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    prompt_version = Column(String(50), nullable=True)
    # Which persona wrote it, for the record. Deliberately not a foreign key: deleting a
    # persona must not take the reports written under it with it, and a report that
    # outlives its persona still says which one it was.
    persona_id = Column(Integer, nullable=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="reports")
    subjects = relationship("ReportSubject", back_populates="report", cascade="all, delete-orphan", order_by="ReportSubject.position")
    approvals = relationship("Approval", back_populates="report", cascade="all, delete-orphan", order_by="Approval.created_at")
    comments = relationship("Comment", back_populates="report", cascade="all, delete-orphan", order_by="Comment.created_at")

    # One weekly report per author, repo and week — but only for weekly reports. With
    # repo_id and week_start nullable a plain UniqueConstraint no longer says that, so
    # it is a partial unique index instead. Declared on the model as well as in the
    # migration or autogenerate reads the real index as drift and writes a revision
    # that drops it (see RepoChunk's HNSW index for the same trap).
    #
    # sqlite_where says the same thing as postgresql_where because each dialect only
    # reads its own kwarg and silently ignores the other's. Without it SQLite built the
    # index unique over ALL rows, so the test suite enforced a rule production does not
    # have: an ad-hoc row duplicating a weekly one was rejected in tests and accepted in
    # Postgres.
    __table_args__ = (
        Index(
            "uq_report_author_repo_week",
            "author_user_id",
            "repo_id",
            "week_start",
            unique=True,
            postgresql_where=text("kind = 'weekly'"),
            sqlite_where=text("kind = 'weekly'"),
        ),
    )

class ReportSubject(Base):
    """One contributor covered by a report, with their own attributed section. A report
    about several people keeps a row each rather than one blended narrative: blending is
    how a generated report ends up crediting one person's work to another."""
    __tablename__ = "report_subjects"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_user_id = Column(Integer, nullable=True, index=True)
    subject_github_login = Column(String(255), nullable=True)
    section = Column(Text, nullable=True)
    position = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    report = relationship("Report", back_populates="subjects")

class Approval(Base):
    """Append-only: rows are never updated or deleted. Report.status is the
    denormalised current state, derived from the latest entry."""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    report = relationship("Report", back_populates="approvals")

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(TIMESTAMP(timezone=True), nullable=True)

    report = relationship("Report", back_populates="comments")

class LlmUsage(Base):
    """One ledger for every surface that spends tokens, not just reports — hence
    `kind`, and hence report_id being null on anything that isn't a report."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(30), nullable=False, server_default=LLM_KIND_REPORT, default=LLM_KIND_REPORT)
    user_id = Column(Integer, nullable=False, index=True)
    # Whose money paid, denormalised the same way reports.dept_id is: null on a personal
    # or platform key. Pulse cannot ask identity which department a user_id sits in, so
    # without this column a department's own spend is unanswerable here.
    dept_id = Column(Integer, nullable=True, index=True)
    tokens = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class GitHubAccount(Base):
    __tablename__ = "github_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    github_user_id = Column(BigInteger, unique=True, index=True, nullable=False)
    github_login = Column(String(255), index=True, nullable=False)
    access_token_encrypted = Column(Text, nullable=False)
    scopes = Column(String(500), nullable=True)
    connected_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    github_repo_id = Column(BigInteger, unique=True, index=True, nullable=False)
    full_name = Column(String(400), index=True, nullable=False)
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
    journals = relationship("RepoJournal", back_populates="repository", cascade="all, delete-orphan")
    journal_rollups = relationship("JournalRollup", back_populates="repository", cascade="all, delete-orphan")

class Commit(Base):
    __tablename__ = "commits"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    sha = Column(String(40), nullable=False)
    author_user_id = Column(Integer, index=True, nullable=True)
    author_github_login = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
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
    # A closed pull request that was never merged has a closed_at and no merged_at, so
    # merged_at alone cannot say when it stopped being open.
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="pull_requests")
    reviews = relationship("Review", back_populates="pull_request", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_pr_repo_number"),)

class Review(Base):
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
    # Who the work is queued to, which is not who raised it. An open issue assigned to
    # someone is the nearest thing GitHub holds to a statement that they intend to do it.
    assignee_user_id = Column(Integer, index=True, nullable=True)
    assignee_github_login = Column(String(255), nullable=True)
    # GitHub's milestone, kept only for its name and its due date: a date somebody set
    # for this work is stated intent, and the only deadline the sync sees.
    milestone_title = Column(String(255), nullable=True)
    milestone_due_on = Column(TIMESTAMP(timezone=True), nullable=True)
    gh_created_at = Column(TIMESTAMP(timezone=True), nullable=True)
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="issues")

    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_issue_repo_number"),)

class SyncRun(Base):
    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=True)
    status = Column(String(20), nullable=False)  # running | success | error | rate_limited | skipped
    detail = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)

    repository = relationship("Repository")

class RepoJournal(Base):
    __tablename__ = "repo_journals"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, nullable=False, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(TIMESTAMP(timezone=True), nullable=True)

    repository = relationship("Repository", back_populates="journals")

class JournalRollup(Base):
    """A snapshot, not a live view: it records the window of entries it read, so a
    rollup stays readable next to the feed it was written from."""
    __tablename__ = "journal_rollups"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    entry_count = Column(Integer, nullable=False)
    covers_from = Column(TIMESTAMP(timezone=True), nullable=True)
    covers_to = Column(TIMESTAMP(timezone=True), nullable=True)
    generated_by_user_id = Column(Integer, nullable=False, index=True)
    model = Column(String(100), nullable=True)
    prompt_version = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    repository = relationship("Repository", back_populates="journal_rollups")

class IndexedRepo(Base):
    """One repository ingested into the chat index. repo_id is null for a public repo
    Pulse has never tracked: those are indexed on request and have no `repositories`
    row to hang off, so full_name is the only identifier they carry."""
    __tablename__ = "indexed_repos"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True)
    full_name = Column(String(400), nullable=False, index=True)
    is_public = Column(Boolean, nullable=False, server_default="false", default=False)
    owner_user_id = Column(Integer, nullable=False, index=True)
    commit_sha = Column(String(40), nullable=True)
    # The commit an ingest is part way through. Set when the run starts and cleared when
    # it finishes, so a non-null value means chunks for that sha are already stored and a
    # retry can pick up where it stopped. commit_sha, above, is the last sha fully indexed.
    ingest_sha = Column(String(40), nullable=True)
    # Which departments the requester belonged to when they asked, comma separated.
    # A Celery task holds a user id and nothing else, and department membership lives in
    # identity, so without this the worker cannot see a department's API key or its token
    # allowance and silently falls back to the platform's. Recorded at request time
    # rather than looked up at run time on purpose: the job is then evaluated against the
    # permissions the requester actually had when they asked, and identity being down
    # cannot change what an ingest is allowed to spend.
    owner_dept_ids = Column(String(400), nullable=True)
    status = Column(String(30), nullable=False, server_default=INDEX_PENDING, default=INDEX_PENDING)
    detail = Column(Text, nullable=True)
    file_count = Column(Integer, nullable=False, server_default="0", default=0)
    chunk_count = Column(Integer, nullable=False, server_default="0", default=0)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    repository = relationship("Repository")
    chunks = relationship("RepoChunk", back_populates="indexed_repo", cascade="all, delete-orphan")
    # No cascade on purpose, and declared only so the ORM does the same thing the
    # ondelete="SET NULL" on the column does: blank the reference, keep the citation.
    citations = relationship("ChatCitation", back_populates="indexed_repo")

    __table_args__ = (UniqueConstraint("owner_user_id", "full_name", name="uq_indexed_repo_owner_full_name"),)

class RepoChunk(Base):
    """A window of one file, with the line numbers it came from. Those numbers are cited
    back to the user next to the answer, so they are 1-indexed and inclusive — the same
    numbering GitHub's line anchors use."""
    __tablename__ = "repo_chunks"

    id = Column(Integer, primary_key=True)
    indexed_repo_id = Column(Integer, ForeignKey("indexed_repos.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(1000), nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_estimate = Column(Integer, nullable=False)
    # SQLite has no vector type. The variant keeps the test suite (and any local SQLite
    # run) able to store an embedding as raw bytes; ranking on that path happens in
    # Python. See repo_index.search_chunks.
    embedding = Column(Vector(EMBEDDING_DIM).with_variant(LargeBinary, "sqlite"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    indexed_repo = relationship("IndexedRepo", back_populates="chunks")

    # Declared on the model, not only in the migration, or autogenerate reads the index
    # Postgres actually has as drift and writes a revision that drops it. The
    # postgresql_* kwargs are ignored by SQLite, which just gets a plain index.
    __table_args__ = (
        Index(
            "ix_repo_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(300), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at, ChatMessage.id")

class ChatMessage(Base):
    """One turn. `model` and `tokens` are null on a question and filled on an answer —
    a question costs nothing and was written by a person, not a model."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    model = Column(String(100), nullable=True)
    tokens = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("ChatConversation", back_populates="messages")
    citations = relationship("ChatCitation", back_populates="message", cascade="all, delete-orphan", order_by="ChatCitation.id")

class ChatCitation(Base):
    """What an answer was grounded in, kept as its own row so the answer above it can be
    checked against the code it claims to describe.

    indexed_repo_id is the one in-service foreign key here that is nullable and SET NULL
    rather than CASCADE, and full_name/path are copied onto the row rather than read
    through it: re-indexing or deleting a repository must not quietly delete an answer's
    evidence, or a months-old conversation turns into unsourced assertions. A null id
    means the index is gone — the citation still says which repo, file and lines it came
    from, it just can no longer be opened in Pulse."""
    __tablename__ = "chat_citations"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    indexed_repo_id = Column(Integer, ForeignKey("indexed_repos.id", ondelete="SET NULL"), nullable=True, index=True)
    full_name = Column(String(400), nullable=False)
    path = Column(String(1000), nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    snippet = Column(Text, nullable=False)

    message = relationship("ChatMessage", back_populates="citations")
    indexed_repo = relationship("IndexedRepo", back_populates="citations")

class Persona(Base):
    """A reusable tone for generated text. owner_user_id NULL means a system preset:
    visible to everyone, editable by no one."""
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    name = Column(String(120), nullable=False)
    length = Column(String(30), nullable=False)
    audience = Column(String(30), nullable=False)
    technical_depth = Column(String(30), nullable=False)
    formality = Column(String(30), nullable=False)
    instructions = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("owner_user_id", "name", name="uq_persona_owner_name"),)

    @property
    def is_system(self) -> bool:
        return self.owner_user_id is None

class TokenBudget(Base):
    """A daily token allowance, overridable at the same three levels as an API key.

    The cap lives in its own table rather than on api_credentials because the two do not
    line up: somebody spending the platform's key has no credential row and still has to
    be able to lower their own allowance. Resolution is user, then department, then the
    platform row, then LLM_DAILY_TOKEN_CAP_PER_USER, which is the same order
    credentials.resolve_credential walks.

    daily_token_cap is a plain integer and 0 means unlimited, matching the setting it
    overrides. Who may raise one is a permission question, not a schema one, and lives in
    services/credentials.py: you may only relax a limit on spend you are paying for.
    """
    __tablename__ = "token_budgets"

    id = Column(Integer, primary_key=True)
    scope = Column(String(20), nullable=False)
    owner_user_id = Column(Integer, nullable=True, index=True)
    dept_id = Column(Integer, nullable=True, index=True)
    daily_token_cap = Column(Integer, nullable=False)
    created_by_user_id = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope", "owner_user_id", "dept_id", name="uq_token_budget_scope"),
    )

class ApiCredential(Base):
    """A customer-supplied LLM key. Whoever's key it is pays for the calls made with it,
    which is why bypass_token_cap lives here and not in settings: the daily cap protects
    the platform's own key, and there is nothing to protect on a key the caller funds.

    The key itself is Fernet-encrypted (app/crypto.py, the same mechanism over GitHub
    tokens) and never leaves the service in plaintext; last_four exists so the UI can
    show which key is installed without holding it."""
    __tablename__ = "api_credentials"

    id = Column(Integer, primary_key=True)
    scope = Column(String(20), nullable=False)
    owner_user_id = Column(Integer, nullable=True, index=True)
    dept_id = Column(Integer, nullable=True, index=True)
    provider = Column(String(30), nullable=False)
    key_encrypted = Column(Text, nullable=False)
    model = Column(String(100), nullable=True)
    last_four = Column(String(8), nullable=False)
    bypass_token_cap = Column(Boolean, nullable=False, server_default="false", default=False)
    created_by_user_id = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope", "owner_user_id", "dept_id", "provider", name="uq_api_credential_scope_provider"),
    )

class PlatformSetting(Base):
    """One row per platform-wide switch, keyed by name.

    Not a column on token_budgets, even though that table already carries a
    platform-scope row: what it holds is a daily cap, and the only payload it has is an
    integer. A visibility switch is not a cap, and hanging it off that row would mean a
    nullable column that means nothing on the user and department rows beside it.
    Neither is it an environment variable, because a platform admin has to be able to
    change it from the product rather than wait for a redeploy.

    The value is stored as text and read through typed accessors in
    services/platform_settings.py, so the next switch needs a constant rather than a
    migration.
    """
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(String(255), nullable=False)
    updated_by_user_id = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

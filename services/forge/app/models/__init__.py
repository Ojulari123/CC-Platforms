# People are referenced by identity `user_id` only; Forge never reads identity's database.
from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, TIMESTAMP, UniqueConstraint, func, text
from sqlalchemy.orm import relationship
from app.db import Base

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, index=True, nullable=True)
    is_sample = Column(Boolean, nullable=False, server_default="false", default=False)
    name = Column(String(200), nullable=False)
    original_filename = Column(String(400), nullable=True)
    content = Column(Text, nullable=False)  # the raw CSV text
    columns = Column(Text, nullable=False)
    row_count = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "uq_sample_name",
            "name",
            unique=True,
            sqlite_where=text("is_sample = 1"),
            postgresql_where=text("is_sample"),
        ),
    )

# What a workflow trains or runs. Kept as plain strings, not an enum type, so adding a
# modality later is a code change and not a Postgres migration on an enum.
KIND_TABULAR_CLASSIFICATION = "tabular_classification"
KIND_TABULAR_REGRESSION = "tabular_regression"
KIND_TIMESERIES_FORECAST = "timeseries_forecast"
KIND_LLM_PLAYGROUND = "llm_playground"
WORKFLOW_KINDS = (KIND_TABULAR_CLASSIFICATION, KIND_TABULAR_REGRESSION, KIND_TIMESERIES_FORECAST, KIND_LLM_PLAYGROUND)

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"

LLM_KIND_PLAYGROUND = "playground"

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    kind = Column(String(40), nullable=False)
    # SET NULL, not CASCADE: deleting a CSV must not silently erase the run history and
    # the generated code that were the point of building the workflow.
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="SET NULL"), index=True, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    steps = relationship("WorkflowStep", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.position")
    # Cascaded by the ORM as well as by the foreign key. The database rule is the one that
    # holds under a raw DELETE; this one is what makes deleting a workflow behave the same
    # on SQLite, where foreign keys are off unless every connection turns them on.
    runs = relationship("WorkflowRun", cascade="all, delete-orphan")

class WorkflowStep(Base):
    """One row per canvas step. This is what lets the UI show each preprocessing choice
    and what the code generator turns into a line of Python; a single blob column would
    give neither surface anything to point at."""
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), index=True, nullable=False)
    position = Column(Integer, nullable=False)
    kind = Column(String(40), nullable=False)
    # JSON as text, the same way datasets.columns is stored: identical on SQLite (tests)
    # and Postgres (deployed), with no dialect-specific column type to keep in step.
    params = Column(Text, nullable=False, server_default="{}", default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    workflow = relationship("Workflow", back_populates="steps")

    __table_args__ = (UniqueConstraint("workflow_id", "position", name="uq_step_position"),)

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), index=True, nullable=False)
    owner_user_id = Column(Integer, index=True, nullable=False)
    status = Column(String(20), nullable=False, server_default=RUN_QUEUED, default=RUN_QUEUED)
    # Learner-readable text only. Tracebacks go to the log, never into this column.
    error = Column(Text, nullable=True)
    metrics = Column(Text, nullable=True)
    # Everything a result page needs without re-running: predictions sample, the resolved
    # feature list, the LLM reply, whatever the run kind produced.
    result = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class LlmUsage(Base):
    """Forge's own token ledger. Deliberately a copy of Pulse's shape rather than an
    import: no service reads or depends on another service's code or database."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(30), nullable=False, server_default=LLM_KIND_PLAYGROUND, default=LLM_KIND_PLAYGROUND)
    user_id = Column(Integer, nullable=False, index=True)
    tokens = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

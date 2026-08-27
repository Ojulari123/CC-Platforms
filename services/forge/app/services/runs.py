"""Starting a run, and what happens inside one.

A run row is written before the work is queued, so a learner sees "queued" immediately
and nothing is lost if the tab closes. execute_run is what the Celery worker calls; it is
also directly callable, which is how the suite exercises the real path without a broker.
"""
import json
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.celery_app import BrokerUnavailableError, dispatch
from app.config import settings
from app.models import DATASET_IMAGE, KIND_IMAGE_CLASSIFICATION, KIND_LLM_PLAYGROUND, KIND_LLM_VISION, LLM_KIND_VISION, LLM_KINDS, RUN_FAILED, RUN_QUEUED, RUN_RUNNING, RUN_SUCCEEDED, Dataset, Workflow, WorkflowRun
from app.services import llm_budget
from app.services import images
from app.services.ai_provider import AIError, describe_image, generate
from app.services.execution import ExecutionError, run_image_classification, run_tabular
from app.services.steps import STEP_PROMPT, STEP_VISION_PROMPT
from app.services.workflows import get_workflow

logger = logging.getLogger(__name__)

# How much of the reply text is kept on the run row. A playground answer is meant to be
# read, not archived, and an unbounded column is how a database fills up.
MAX_STORED_REPLY = 20_000

def start_run(db: Session, workflow_id: int, user_id: int) -> WorkflowRun:
    workflow = get_workflow(db, workflow_id, user_id)
    if not workflow.steps:
        raise HTTPException(status_code=400, detail="This workflow has no steps yet, so there is nothing to run.")
    if workflow.kind in LLM_KINDS:
        # Refused before the money is spent, not reported after. Same reason Pulse checks
        # up front: a cap that only notices afterwards is not a cap.
        params = json.loads(workflow.steps[0].params or "{}")
        about_to_spend = llm_budget.estimate_tokens(f"{params.get('system', '')}\n{params.get('prompt', '')}\n{params.get('context', '')}") + int(params.get("max_tokens", 500))
        if workflow.kind == KIND_LLM_VISION:
            # An image is billed by how many tiles it covers, and none of that shows up in
            # the text, so it is added as a flat figure rather than left out of the cap.
            about_to_spend += settings.CAPTION_IMAGE_TOKEN_ESTIMATE
        try:
            llm_budget.check_budget(db, user_id, about_to_spend=about_to_spend)
        except llm_budget.BudgetExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc))
    # The playground is the only kind with nothing attached. An image question needs the
    # dataset the image lives in, the same as a training run needs its data.
    if workflow.kind != KIND_LLM_PLAYGROUND:
        if workflow.dataset_id is None or db.get(Dataset, workflow.dataset_id) is None:
            # The row, not just the id: a deleted dataset only nulls the column where
            # foreign keys are enforced, and the learner should hear about it before a run
            # is queued.
            raise HTTPException(status_code=400, detail="The dataset this workflow used has been deleted. Attach another one before running it.")

    run = WorkflowRun(workflow_id=workflow.id, owner_user_id=user_id, status=RUN_QUEUED)
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        from app.tasks import execute_run as execute_run_task

        dispatch(execute_run_task, run.id)
    except BrokerUnavailableError as exc:
        run.status = RUN_FAILED
        run.error = str(exc)
        db.commit()
        db.refresh(run)
        raise HTTPException(status_code=503, detail=str(exc))
    return run

def list_runs(db: Session, workflow_id: int, user_id: int, limit: int, offset: int) -> tuple[list[WorkflowRun], int]:
    get_workflow(db, workflow_id, user_id)
    where = WorkflowRun.workflow_id == workflow_id
    total = db.scalar(select(func.count()).select_from(WorkflowRun).where(where)) or 0
    window = list(db.scalars(select(WorkflowRun).where(where).order_by(WorkflowRun.id.desc()).limit(limit).offset(offset)))
    return window, total

def get_run(db: Session, workflow_id: int, run_id: int, user_id: int) -> WorkflowRun:
    get_workflow(db, workflow_id, user_id)
    run = db.get(WorkflowRun, run_id)
    if run is None or run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

def _run_llm(db: Session, workflow: Workflow, run: WorkflowRun) -> tuple[dict, dict]:
    step = next(s for s in workflow.steps if s.kind == STEP_PROMPT)
    params = json.loads(step.params or "{}")
    prompt, context = params.get("prompt", ""), params.get("context") or ""
    user_message = f"{prompt}\n\nUse only this text:\n{context}" if context else prompt
    try:
        result = generate(params.get("system") or "You are a helpful assistant.", user_message, max_tokens=params.get("max_tokens", 500))
    except AIError as exc:
        raise ExecutionError(str(exc))
    tokens = result.token_count or llm_budget.estimate_tokens(user_message)
    llm_budget.record_usage(db, user_id=run.owner_user_id, run_id=run.id, tokens=tokens)
    return {"tokens": tokens}, {"model": result.model, "reply": result.text[:MAX_STORED_REPLY], "prompt": prompt, "grounded": bool(context)}

def _run_vision(db: Session, workflow: Workflow, run: WorkflowRun) -> tuple[dict, dict]:
    step = next(s for s in workflow.steps if s.kind == STEP_VISION_PROMPT)
    params = json.loads(step.params or "{}")
    dataset = db.get(Dataset, workflow.dataset_id) if workflow.dataset_id else None
    if dataset is None or dataset.kind != DATASET_IMAGE or not dataset.content_blob:
        raise ExecutionError("The image dataset this workflow used is gone. Attach another one before running it.")
    try:
        raw = images.read_image_bytes(dataset.content_blob, params["image"])
        prepared, mime = images.shrink_for_vision(raw)
    except images.ImageDatasetError as exc:
        raise ExecutionError(str(exc))
    prompt = params.get("prompt") or ""
    try:
        result = describe_image(params.get("system") or "", prompt, prepared, mime=mime, max_tokens=params.get("max_tokens", 300))
    except AIError as exc:
        raise ExecutionError(str(exc))
    tokens = result.token_count or llm_budget.estimate_tokens(prompt) + settings.CAPTION_IMAGE_TOKEN_ESTIMATE
    llm_budget.record_usage(db, user_id=run.owner_user_id, run_id=run.id, tokens=tokens, kind=LLM_KIND_VISION)
    return {"tokens": tokens}, {
        "model": result.model,
        "reply": result.text[:MAX_STORED_REPLY],
        "prompt": prompt,
        "image": params["image"],
        "sent_bytes": len(prepared),
        "sent_max_edge": settings.CAPTION_MAX_EDGE,
    }

def execute_run(db: Session, run_id: int) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} no longer exists")
    workflow = db.get(Workflow, run.workflow_id)
    # Held as a local because the commit below expires the attribute, and SQLite hands
    # the value back naive, which will not subtract from an aware datetime.
    started = datetime.now(timezone.utc)
    run.status = RUN_RUNNING
    run.started_at = started
    db.commit()

    try:
        if workflow.kind == KIND_LLM_PLAYGROUND:
            metrics, result = _run_llm(db, workflow, run)
        elif workflow.kind == KIND_LLM_VISION:
            metrics, result = _run_vision(db, workflow, run)
        elif workflow.kind == KIND_IMAGE_CLASSIFICATION:
            dataset = db.get(Dataset, workflow.dataset_id) if workflow.dataset_id else None
            if dataset is None or dataset.kind != DATASET_IMAGE or not dataset.content_blob:
                raise ExecutionError("The image dataset this workflow used has been deleted, so there is nothing to train on.")
            try:
                manifest = images.manifest_from_text(dataset.content)
            except images.ImageDatasetError as exc:
                raise ExecutionError(str(exc))
            metrics, result = run_image_classification(dataset.content_blob, manifest, workflow.steps)
            result["dataset"] = dataset.name
        else:
            dataset = db.get(Dataset, workflow.dataset_id) if workflow.dataset_id else None
            if dataset is None:
                raise ExecutionError("The dataset this workflow used has been deleted, so there is nothing to train on.")
            metrics, result = run_tabular(workflow.kind, dataset.content, workflow.steps)
            result["dataset"] = dataset.name
        run.status = RUN_SUCCEEDED
        run.metrics = json.dumps(metrics)
        run.result = json.dumps(result)
        run.error = None
    except ExecutionError as exc:
        run.status = RUN_FAILED
        run.error = str(exc)
    except Exception as exc:
        # Anything unforeseen. The traceback goes to the log, where it is useful; the
        # learner gets a sentence, because a stack trace is a message about Forge.
        logger.exception("run %s failed unexpectedly", run_id)
        run.status = RUN_FAILED
        run.error = f"Something went wrong while running this workflow ({exc.__class__.__name__}). The details are in the server log."
    finished = datetime.now(timezone.utc)
    run.finished_at = finished
    run.duration_ms = int((finished - started).total_seconds() * 1000)
    db.commit()
    db.refresh(run)
    return run

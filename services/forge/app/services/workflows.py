"""Workflow CRUD and the ownership rule.

Someone else's workflow answers 404, not 403: a 403 confirms the thing exists, and who
owns which workflow is not the caller's business.
"""
import json
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.models import WORKFLOW_KINDS, KIND_LLM_PLAYGROUND, Workflow, WorkflowStep
from app.services.datasets import get_dataset
from app.services.steps import StepError, validate_sequence

NOT_FOUND = "Workflow not found"

def _step_rows(kind: str, steps: list[tuple[str, dict]]) -> list[WorkflowStep]:
    """Raises StepError, which every caller turns into a 400."""
    cleaned = validate_sequence(kind, steps)
    return [
        WorkflowStep(position=index, kind=step_kind, params=json.dumps(params))
        for index, ((step_kind, _), params) in enumerate(zip(steps, cleaned, strict=True))
    ]

def create_workflow(db: Session, *, owner_user_id: int, name: str, kind: str, dataset_id: int | None, steps: list[tuple[str, dict]]) -> Workflow:
    if kind not in WORKFLOW_KINDS:
        raise HTTPException(status_code=400, detail=f"'{kind}' is not a workflow kind. Choose one of: {', '.join(WORKFLOW_KINDS)}.")
    if kind != KIND_LLM_PLAYGROUND:
        if dataset_id is None:
            raise HTTPException(status_code=400, detail="This workflow kind needs a dataset to learn from.")
        get_dataset(db, dataset_id, owner_user_id)  # 404/403 from the dataset rules
    workflow = Workflow(owner_user_id=owner_user_id, name=name, kind=kind, dataset_id=dataset_id if kind != KIND_LLM_PLAYGROUND else None)
    try:
        workflow.steps = _step_rows(kind, steps)
    except StepError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow

def list_workflows(db: Session, owner_user_id: int, limit: int, offset: int) -> tuple[list[Workflow], int]:
    where = Workflow.owner_user_id == owner_user_id
    total = db.scalar(select(func.count()).select_from(Workflow).where(where)) or 0
    window = list(db.scalars(
        select(Workflow)
        .where(where)
        .options(selectinload(Workflow.steps))
        .order_by(Workflow.created_at.desc(), Workflow.id.desc())
        .limit(limit)
        .offset(offset)
    ))
    return window, total

def get_workflow(db: Session, workflow_id: int, user_id: int) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return workflow

def replace_steps(db: Session, workflow_id: int, user_id: int, steps: list[tuple[str, dict]]) -> Workflow:
    workflow = get_workflow(db, workflow_id, user_id)
    try:
        rows = _step_rows(workflow.kind, steps)
    except StepError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Positions are unique per workflow, and SQLAlchemy will happily insert the new rows
    # before deleting the old ones inside one flush. Deleting first is what stops the two
    # sets colliding on that constraint.
    for existing in list(workflow.steps):
        db.delete(existing)
    db.flush()
    workflow.steps = rows
    db.commit()
    db.refresh(workflow)
    return workflow

def delete_workflow(db: Session, workflow_id: int, user_id: int) -> None:
    workflow = get_workflow(db, workflow_id, user_id)
    db.delete(workflow)
    db.commit()

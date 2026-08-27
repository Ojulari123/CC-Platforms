import json
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.models import DATASET_IMAGE
from app.config import settings
from app.db import get_db
from app.rate_limit import limiter
from app.schemas.workflows import GeneratedCode, RunResponse, StepsUpdate, WorkflowCreate, WorkflowResponse
from app.services import codegen, runs as run_service, workflows as workflow_service
from app.services.datasets import get_dataset
from app.services.steps import STEP_CATALOG, STEPS_FOR_KIND

router = APIRouter(prefix="/workflows", tags=["workflows"])

def _pairs(steps) -> list[tuple[str, dict]]:
    return [(s.kind, s.params) for s in steps]

@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_workflow(request: Request, payload: WorkflowCreate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> WorkflowResponse:
    return workflow_service.create_workflow(db, owner_user_id=user.user_id, name=payload.name, kind=payload.kind, dataset_id=payload.dataset_id, steps=_pairs(payload.steps))

@router.get("", response_model=Page[WorkflowResponse])
@limiter.limit("60/minute")
def list_workflows(request: Request, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[WorkflowResponse]:
    items, total = workflow_service.list_workflows(db, user.user_id, limit=page.limit, offset=page.offset)
    return Page.of([WorkflowResponse.model_validate(w) for w in items], total=total, params=page)

# Declared before /{workflow_id} so "steps" isn't swallowed by the int path param.
@router.get("/steps", tags=["workflows"])
@limiter.limit("60/minute")
def step_catalog(request: Request, user: TokenClaims = Depends(current_user)) -> dict:
    """What the canvas can offer. The UI reads its palette from here rather than keeping
    a second copy of the vocabulary that can drift from the one the server enforces."""
    return {"steps": STEP_CATALOG, "steps_by_workflow_kind": {kind: list(steps) for kind, steps in STEPS_FOR_KIND.items()}}

@router.get("/{workflow_id}", response_model=WorkflowResponse)
@limiter.limit("60/minute")
def get_workflow(request: Request, workflow_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> WorkflowResponse:
    return workflow_service.get_workflow(db, workflow_id, user.user_id)

@router.put("/{workflow_id}/steps", response_model=WorkflowResponse)
@limiter.limit("30/minute")
def replace_steps(request: Request, workflow_id: int, payload: StepsUpdate, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> WorkflowResponse:
    return workflow_service.replace_steps(db, workflow_id, user.user_id, _pairs(payload.steps))

@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_workflow(request: Request, workflow_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    workflow_service.delete_workflow(db, workflow_id, user.user_id)

@router.post("/{workflow_id}/runs", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/minute")
def start_run(request: Request, workflow_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RunResponse:
    return run_service.start_run(db, workflow_id, user.user_id)

@router.get("/{workflow_id}/runs", response_model=Page[RunResponse])
@limiter.limit("60/minute")
def list_runs(request: Request, workflow_id: int, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[RunResponse]:
    items, total = run_service.list_runs(db, workflow_id, user.user_id, limit=page.limit, offset=page.offset)
    return Page.of([RunResponse.model_validate(r) for r in items], total=total, params=page)

@router.get("/{workflow_id}/runs/{run_id}", response_model=RunResponse)
@limiter.limit("120/minute")
def get_run(request: Request, workflow_id: int, run_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> RunResponse:
    return run_service.get_run(db, workflow_id, run_id, user.user_id)

@router.get("/{workflow_id}/code", response_model=GeneratedCode)
@limiter.limit("30/minute")
def generated_code(request: Request, workflow_id: int, fmt: str = Query(default="script", pattern="^(script|notebook)$"), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> GeneratedCode:
    """The script the canvas describes. Returned as text rather than a download so the UI
    can show it next to the steps it came from, which is the point of the export."""
    workflow = workflow_service.get_workflow(db, workflow_id, user.user_id)
    data_path = "data.csv"
    if workflow.dataset_id:
        dataset = get_dataset(db, workflow.dataset_id, user.user_id)
        # An image script reads a folder the learner unzipped, not a file, so the path it
        # is handed has to be a directory name rather than the archive's.
        data_path = "images" if dataset.kind == DATASET_IMAGE else (dataset.original_filename or f"{dataset.name}.csv")
    if fmt == "notebook":
        notebook = codegen.generate_notebook(workflow, workflow.steps, data_path=data_path, model=settings.LLM_MODEL)
        return GeneratedCode(filename=codegen.notebook_filename(workflow), language="ipynb", code=json.dumps(notebook, indent=1))
    return GeneratedCode(filename=codegen.script_filename(workflow), language="python", code=codegen.generate_script(workflow, workflow.steps, data_path=data_path, model=settings.LLM_MODEL))

@router.get("/{workflow_id}/code/raw", response_class=PlainTextResponse)
@limiter.limit("30/minute")
def generated_code_raw(request: Request, workflow_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> PlainTextResponse:
    """Same script, as a file the browser can save straight to disk."""
    body = generated_code(request, workflow_id, "script", user, db)
    return PlainTextResponse(body.code, media_type="text/x-python", headers={"Content-Disposition": f'attachment; filename="{body.filename}"'})

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session
from crescent_core import Page, PageParams, TokenClaims, page_params
from app.auth import current_user
from app.config import settings
from app.db import get_db
from app.rate_limit import limiter
from app.schemas.datasets import DatasetPreview, DatasetResponse, DatasetSummary, ImageDatasetManifest
from app.services import datasets as dataset_service
from app.services.steps import FLATTENED_PIXEL_CAVEAT

router = APIRouter(prefix="/datasets", tags=["datasets"])

_UPLOAD_CHUNK = 1024 * 1024  # 1 MB read window

async def _read_capped(file: UploadFile, limit_mb: int | None = None) -> bytes:
    """Read the upload in chunks and bail the moment it crosses the limit, so an
    oversized (or endless) body never gets fully buffered into memory."""
    limit_mb = settings.MAX_UPLOAD_MB if limit_mb is None else limit_mb
    limit = limit_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"File exceeds the {limit_mb} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)

@router.post("", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_dataset(request: Request, file: UploadFile = File(...), name: str | None = Form(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> DatasetResponse:
    raw = await _read_capped(file)
    dataset = dataset_service.create_dataset(
        db,
        owner_user_id=user.user_id,
        name=name or file.filename or "dataset",
        original_filename=file.filename,
        raw_bytes=raw,
    )
    return dataset

@router.post("/images", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def upload_image_dataset(request: Request, file: UploadFile = File(...), name: str | None = Form(default=None), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> DatasetResponse:
    """A ZIP with one folder per class, or a single image to ask questions about."""
    raw = await _read_capped(file, settings.MAX_IMAGE_UPLOAD_MB)
    return dataset_service.create_image_dataset(
        db,
        owner_user_id=user.user_id,
        name=name or file.filename or "images",
        original_filename=file.filename,
        raw_bytes=raw,
    )

@router.get("", response_model=Page[DatasetResponse])
@limiter.limit("60/minute")
def list_datasets(request: Request, page: PageParams = Depends(page_params), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> Page[DatasetResponse]:
    items, total = dataset_service.list_datasets(db, user.user_id, limit=page.limit, offset=page.offset)
    return Page.of([DatasetResponse.model_validate(d) for d in items], total=total, params=page)

# Declared before /{dataset_id} so "summary" isn't swallowed by the int path param.
@router.get("/summary", response_model=DatasetSummary)
@limiter.limit("60/minute")
def summarize_datasets(request: Request, recent: int = Query(default=5, ge=0, le=20), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> DatasetSummary:
    owned_count, sample_count, newest = dataset_service.summarize_datasets(db, user.user_id, recent)
    return DatasetSummary(
        owned_count=owned_count,
        sample_count=sample_count,
        recent=[DatasetResponse.model_validate(d) for d in newest],
    )

@router.get("/{dataset_id}", response_model=DatasetResponse)
@limiter.limit("60/minute")
def get_dataset(request: Request, dataset_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> DatasetResponse:
    return dataset_service.get_dataset(db, dataset_id, user.user_id)

@router.get("/{dataset_id}/preview", response_model=DatasetPreview)
@limiter.limit("30/minute")
def preview_dataset(request: Request, dataset_id: int, rows: int = Query(default=settings.DATASET_PREVIEW_ROWS, ge=1, le=500), user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> DatasetPreview:
    return dataset_service.preview_dataset(db, dataset_id, user.user_id, rows)

@router.get("/{dataset_id}/images", response_model=ImageDatasetManifest)
@limiter.limit("30/minute")
def image_manifest(request: Request, dataset_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> ImageDatasetManifest:
    """What is in an image dataset: the classes, how many images each holds, and the name
    of every image, which is what a vision step points at."""
    manifest = dataset_service.image_manifest(db, dataset_id, user.user_id)
    return ImageDatasetManifest(**manifest, method_note=FLATTENED_PIXEL_CAVEAT)

@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_dataset(request: Request, dataset_id: int, user: TokenClaims = Depends(current_user), db: Session = Depends(get_db)) -> None:
    dataset_service.delete_dataset(db, dataset_id, user.user_id)

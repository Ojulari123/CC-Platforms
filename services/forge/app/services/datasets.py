import csv
import io
import json
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer
from app.config import settings
from app.models import Dataset
from app.samples import SAMPLE_DATASETS
from app.schemas.datasets import DatasetPreview

def _parse_csv(raw_bytes: bytes) -> tuple[str, list[str], int]:
    if len(raw_bytes) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text")
    if not text.strip():
        raise HTTPException(status_code=400, detail="File is empty")
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail=f"Malformed CSV: {exc}")
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    header = rows[0]
    if not header:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    row_count = len(rows) - 1
    return text, header, row_count

def create_dataset(db: Session, owner_user_id: int, name: str, original_filename: str | None, raw_bytes: bytes) -> Dataset:
    text, header, row_count = _parse_csv(raw_bytes)
    dataset = Dataset(
        owner_user_id=owner_user_id,
        is_sample=False,
        name=name,
        original_filename=original_filename,
        content=text,
        columns=json.dumps(header),
        row_count=row_count,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset

def list_datasets(db: Session, owner_user_id: int, limit: int, offset: int) -> tuple[list[Dataset], int]:
    visible = or_(Dataset.owner_user_id == owner_user_id, Dataset.is_sample.is_(True))
    total = db.scalar(select(func.count()).select_from(Dataset).where(visible)) or 0
    window = list(db.scalars(
        select(Dataset)
        .where(visible)
        .options(defer(Dataset.content))
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
        .limit(limit)
        .offset(offset)
    ))
    return window, total

def summarize_datasets(db: Session, owner_user_id: int, recent: int) -> tuple[int, int, list[Dataset]]:
    # Counts are two cheap COUNTs rather than a paged walk. Samples belong to
    # nobody, so "owned" is deliberately exclusive of them.
    owned_count = db.scalar(
        select(func.count()).select_from(Dataset).where(Dataset.owner_user_id == owner_user_id, Dataset.is_sample.is_(False))
    ) or 0
    sample_count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_sample.is_(True))) or 0
    visible = or_(Dataset.owner_user_id == owner_user_id, Dataset.is_sample.is_(True))
    newest = list(db.scalars(
        select(Dataset)
        .where(visible)
        .options(defer(Dataset.content))
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
        .limit(recent)
    )) if recent else []
    return owned_count, sample_count, newest

def get_dataset(db: Session, dataset_id: int, user_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if dataset.is_sample or dataset.owner_user_id == user_id:
        return dataset
    raise HTTPException(status_code=403, detail="Not your dataset")

def preview_dataset(db: Session, dataset_id: int, user_id: int, rows: int) -> DatasetPreview:
    dataset = get_dataset(db, dataset_id, user_id)
    parsed = list(csv.reader(io.StringIO(dataset.content)))
    header = parsed[0] if parsed else json.loads(dataset.columns)
    data_rows = parsed[1:]
    preview_rows = data_rows[:rows]
    return DatasetPreview(
        columns=header,
        rows=preview_rows,
        row_count=dataset.row_count,
        truncated=dataset.row_count > len(preview_rows),
    )

def delete_dataset(db: Session, dataset_id: int, user_id: int) -> None:
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if dataset.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can delete a dataset")
    db.delete(dataset)
    db.commit()

def seed_sample_datasets(db: Session) -> None:
    existing = db.scalar(select(Dataset.id).where(Dataset.is_sample.is_(True)).limit(1))
    if existing is not None:
        return
    for name, filename, content in SAMPLE_DATASETS:
        _, header, row_count = _parse_csv(content.encode("utf-8"))
        try:
            # SAVEPOINT per sample so a lost race rolls back only that one insert,
            # not any sibling sample already flushed in this transaction.
            with db.begin_nested():
                db.add(Dataset(
                    owner_user_id=None,
                    is_sample=True,
                    name=name,
                    original_filename=filename,
                    content=content,
                    columns=json.dumps(header),
                    row_count=row_count,
                ))
        except IntegrityError:
            pass  # another worker already seeded this sample
    db.commit()

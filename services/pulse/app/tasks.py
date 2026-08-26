import logging
from app.celery_app import celery
from app.db import SessionLocal
from app.services import repo_index as repo_index_service, sync as sync_service

logger = logging.getLogger(__name__)

@celery.task(name="app.tasks.sync_all_repos")
def sync_all_repos() -> int:
    db = SessionLocal()
    try:
        runs = sync_service.run_full_sync(db)
        logger.info("sync_all_repos: %d run(s) — %s", len(runs), ", ".join(r.status for r in runs))
        return len(runs)
    finally:
        db.close()

@celery.task(name="app.tasks.index_repo")
def index_repo(indexed_repo_id: int) -> str:
    db = SessionLocal()
    try:
        row = repo_index_service.ingest_repo(db, indexed_repo_id=indexed_repo_id)
        logger.info("index_repo: %s -> %s (%d chunk(s))", row.full_name, row.status, row.chunk_count)
        return row.status
    finally:
        db.close()

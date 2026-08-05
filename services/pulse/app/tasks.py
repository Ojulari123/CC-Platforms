import logging
from app.celery_app import celery
from app.db import SessionLocal
from app.services import sync as sync_service

logger = logging.getLogger(__name__)

@celery.task(name="app.tasks.sync_all_repos")
def sync_all_repos() -> int:
    """Fired daily by beat (and callable on demand). Runs one sync pass over the
    allowlist and returns how many repo runs it wrote."""
    db = SessionLocal()
    try:
        runs = sync_service.run_full_sync(db)
        logger.info("sync_all_repos: %d run(s) — %s", len(runs), ", ".join(r.status for r in runs))
        return len(runs)
    finally:
        db.close()

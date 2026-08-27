import logging
from app.celery_app import celery
from app.db import SessionLocal
from app.services import runs as run_service

logger = logging.getLogger(__name__)

@celery.task(name="app.tasks.execute_run")
def execute_run(run_id: int) -> str:
    """Training is minutes of CPU, so it never runs in a request thread."""
    db = SessionLocal()
    try:
        run = run_service.execute_run(db, run_id)
        logger.info("execute_run %s -> %s", run_id, run.status)
        return run.status
    finally:
        db.close()

from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery = Celery(
    "pulse",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery.conf.update(
    task_track_started=True,
    timezone="UTC",
    beat_schedule={
        "daily-github-sync": {
            "task": "app.tasks.sync_all_repos",
            "schedule": crontab(hour=settings.SYNC_HOUR_UTC, minute=0),
        },
    },
)

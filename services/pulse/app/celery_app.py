"""Celery wiring for Pulse's background jobs.

Celery = the thing that runs work outside the web request. Redis is both the
"broker" (the queue of jobs waiting to run) and the result backend. A "beat"
schedule fires the daily GitHub sync so data refreshes without anyone clicking
refresh — that's the Week-3 "done when".

Only the worker and beat processes import this (see docker-compose). The web app
(app.main) stays lean and doesn't depend on Celery. Tasks live in app.tasks.
"""
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

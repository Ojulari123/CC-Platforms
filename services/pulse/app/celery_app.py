import logging
from celery import Celery
from celery.schedules import crontab
from app.config import settings

logger = logging.getLogger(__name__)

celery = Celery(
    "pulse",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

# A queue is either reachable or it is not, and a request thread should not spend twenty
# seconds finding that out. task.delay() subscribes to the result backend before it
# publishes, and celery's default backend policy retries that twenty times a second apart,
# so a refusal took 19s from a cold process. Two retries at most, and a bounded connect,
# put the 503 back within a couple of seconds. Only connect timeouts are set: a read
# timeout would also apply to the worker's blocking pop off the queue.
_FAIL_FAST_RETRY = {"max_retries": 1, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}
_CONNECT_TIMEOUT = 2

celery.conf.update(
    task_track_started=True,
    timezone="UTC",
    broker_connection_timeout=_CONNECT_TIMEOUT,
    broker_transport_options={"socket_connect_timeout": _CONNECT_TIMEOUT},
    task_publish_retry_policy=_FAIL_FAST_RETRY,
    redis_socket_connect_timeout=_CONNECT_TIMEOUT,
    result_backend_transport_options={
        "socket_connect_timeout": _CONNECT_TIMEOUT,
        "retry_policy": _FAIL_FAST_RETRY,
    },
    beat_schedule={
        "daily-github-sync": {
            "task": "app.tasks.sync_all_repos",
            "schedule": crontab(hour=settings.SYNC_HOUR_UTC, minute=0),
        },
    },
)

class BrokerUnavailableError(Exception):
    """Stands in for whatever kombu or redis-py threw, so a caller answers with one
    message instead of a 500 carrying a connection string."""

BROKER_UNAVAILABLE_DETAIL = "Background processing is temporarily unavailable. Try again shortly."

def dispatch(task, *args):
    """Every enqueue goes through here. A broker that is down is an infrastructure
    problem, not the caller's, and it must not reach them as provider text."""
    try:
        return task.delay(*args)
    except Exception as exc:  # kombu OperationalError, redis ConnectionError, DNS, timeouts
        logger.warning("could not queue %s (%s)", task.name, exc)
        raise BrokerUnavailableError(BROKER_UNAVAILABLE_DETAIL) from exc

import logging
from celery import Celery
from app.config import settings

logger = logging.getLogger(__name__)

celery = Celery(
    "forge",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

# Same fail-fast policy as Pulse: task.delay() subscribes to the result backend before it
# publishes, and celery's default retry policy turns an unreachable broker into a
# nineteen-second wait inside a request. Only connect timeouts are set, because a read
# timeout would also cut the worker's blocking pop off the queue.
_FAIL_FAST_RETRY = {"max_retries": 1, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}
_CONNECT_TIMEOUT = 2

# Its own queue, for the reason spelled out in Pulse's celery_app.py: one Redis, two
# products, and celery's default queue name is the same string in both. Set here rather
# than on the worker command line so a new task cannot land on Pulse's worker.
celery.conf.update(
    task_track_started=True,
    task_default_queue="forge",
    timezone="UTC",
    broker_connection_timeout=_CONNECT_TIMEOUT,
    broker_transport_options={"socket_connect_timeout": _CONNECT_TIMEOUT},
    task_publish_retry_policy=_FAIL_FAST_RETRY,
    redis_socket_connect_timeout=_CONNECT_TIMEOUT,
    result_backend_transport_options={
        "socket_connect_timeout": _CONNECT_TIMEOUT,
        "retry_policy": _FAIL_FAST_RETRY,
    },
)

class BrokerUnavailableError(Exception):
    """Stands in for whatever kombu or redis-py threw, so a caller answers with one
    message instead of a 500 carrying a connection string."""

BROKER_UNAVAILABLE_DETAIL = "Training is temporarily unavailable. Try again shortly."

def dispatch(task, *args):
    """Every enqueue goes through here. A broker that is down is an infrastructure
    problem, not the learner's, and it must not reach them as connection text."""
    try:
        return task.delay(*args)
    except Exception as exc:  # kombu OperationalError, redis ConnectionError, DNS, timeouts
        logger.warning("could not queue %s (%s)", task.name, exc)
        raise BrokerUnavailableError(BROKER_UNAVAILABLE_DETAIL) from exc

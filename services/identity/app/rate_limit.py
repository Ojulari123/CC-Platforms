"""Per-IP rate limiting on the auth endpoints (slowapi, ported from FindYourCribb).

In-memory storage — resets on restart, per-process. Fine for a single dev
container; swap storage_uri to Redis when Redis lands for Celery so limits
hold across replicas."""
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

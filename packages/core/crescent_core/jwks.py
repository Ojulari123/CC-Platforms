import threading
import time
from typing import Callable
import httpx

class JWKSClient:
    """An unknown kid triggers a refresh, floored by min_refresh_interval_seconds: auth
    runs before the rate limiter, so made-up kids could otherwise hammer identity once
    per request."""

    def __init__(self, jwks_url: str, ttl_seconds: int = 3600, timeout_seconds: float = 5.0, fetcher: Callable[[], dict] | None = None, min_refresh_interval_seconds: float = 30.0):
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._fetcher = fetcher or self._http_fetcher
        self._min_refresh_interval = min_refresh_interval_seconds
        self._cache: dict[str, dict] = {}
        self._cache_expires_at = 0.0
        self._last_attempt_at = 0.0
        self._last_error: Exception | None = None
        # Guards the attempt timestamp only. The fetch itself happens outside it so
        # concurrent verifications never queue behind someone else's HTTP call.
        self._lock = threading.Lock()

    def _http_fetcher(self) -> dict:
        resp = httpx.get(self._jwks_url, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def get_key(self, kid: str | None) -> dict | None:
        now = time.time()
        if now >= self._cache_expires_at or (kid and kid not in self._cache):
            self._maybe_refresh(now)
        key = self._cache.get(kid) if kid else None
        if key is None and not self._cache and self._last_error is not None:
            # Nothing cached and identity is unreachable: surface that instead of
            # letting it read as "your token is bad". Once we hold keys we stay quiet.
            raise self._last_error
        return key

    def _maybe_refresh(self, now: float) -> None:
        with self._lock:
            if now - self._last_attempt_at < self._min_refresh_interval:
                return
            self._last_attempt_at = now
        try:
            payload = self._fetcher()
        except Exception as e:
            self._last_error = e
            return
        keys = payload.get("keys", []) if isinstance(payload, dict) else []
        parsed = {k["kid"]: k for k in keys if k.get("kid")}
        if not parsed:
            # An empty or unparseable document is far likelier to be a bad response
            # than identity genuinely publishing no keys. Keep what we have.
            self._last_error = ValueError("JWKS document contained no usable keys")
            return
        self._cache = parsed
        self._cache_expires_at = time.time() + self._ttl
        self._last_error = None

    def invalidate(self) -> None:
        self._cache_expires_at = 0.0
        self._last_attempt_at = 0.0

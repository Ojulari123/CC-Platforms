import time
from typing import Callable
import httpx

class JWKSClient:
    """Fetches identity's JWKS document and caches keys by kid.

    - TTL refresh keeps rotations flowing without a restart.
    - Unknown-kid triggers an immediate refresh (handles fresh rotations before TTL).
    - Fetcher is injectable so tests can supply a JWKS dict without patching httpx."""

    def __init__(self, jwks_url: str, ttl_seconds: int = 3600, timeout_seconds: float = 5.0, fetcher: Callable[[], dict] | None = None):
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._fetcher = fetcher or self._http_fetcher
        self._cache: dict[str, dict] = {}
        self._cache_expires_at = 0.0

    def _http_fetcher(self) -> dict:
        resp = httpx.get(self._jwks_url, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def get_key(self, kid: str | None) -> dict | None:
        """Return the JWK for kid, refreshing cache if expired or if kid is unknown.
        Two refreshes at most per call: TTL check, then unknown-kid check."""
        now = time.time()
        if now >= self._cache_expires_at:
            self._refresh()
        if kid and kid not in self._cache:
            self._refresh()
        return self._cache.get(kid) if kid else None

    def _refresh(self) -> None:
        payload = self._fetcher()
        keys = payload.get("keys", []) if isinstance(payload, dict) else []
        self._cache = {k["kid"]: k for k in keys if k.get("kid")}
        self._cache_expires_at = time.time() + self._ttl

    def invalidate(self) -> None:
        """Force the next get_key() to re-fetch. Useful if the caller knows a
        rotation just happened."""
        self._cache_expires_at = 0.0

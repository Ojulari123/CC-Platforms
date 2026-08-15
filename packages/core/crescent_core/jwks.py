import threading
import time
from typing import Callable
import httpx

# Long enough that inbound traffic can't be turned into outbound fetches one for one,
# short enough that a blip costs a cold process about a second rather than half a minute.
COLD_RETRY_INTERVAL_SECONDS = 1.0

class JWKSUnavailable(httpx.HTTPError):
    """Nothing cached and identity could not supply any keys. Never means the token is
    bad: nothing has been proven about it either way.

    Subclasses httpx.HTTPError so callers written before this type existed keep working
    — the rate limiters in pulse and forge catch httpx.HTTPError to fall back to
    address-keyed limits when a token can't be verified. The base class can go once
    those catch JWKSUnavailable by name."""

class JWKSClient:
    """An unknown kid triggers a refresh, floored by min_refresh_interval_seconds: auth
    runs before the rate limiter, so made-up kids could otherwise hammer identity once
    per request. The floor drops to cold_retry_interval_seconds while nothing is cached,
    where there is no forgery to shield against and a failed first fetch would otherwise
    strand the process for the full interval."""

    def __init__(self, jwks_url: str, ttl_seconds: int = 3600, timeout_seconds: float = 5.0, fetcher: Callable[[], dict] | None = None, min_refresh_interval_seconds: float = 30.0, cold_retry_interval_seconds: float = COLD_RETRY_INTERVAL_SECONDS):
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._fetcher = fetcher or self._http_fetcher
        self._min_refresh_interval = min_refresh_interval_seconds
        self._cold_retry_interval = min(cold_retry_interval_seconds, min_refresh_interval_seconds)
        self._cache: dict[str, dict] = {}
        self._cache_expires_at = 0.0
        self._last_attempt_at = 0.0
        self._last_error: Exception | None = None
        # Guards the bookkeeping below only. The fetch itself happens outside it so
        # concurrent verifications never queue behind someone else's HTTP call.
        self._lock = threading.Lock()
        # Set while one caller is fetching. Everyone else waits on it instead of
        # returning early, which on a cold process meant reading an empty cache and
        # reporting a perfectly good token as "Unknown signing key".
        self._inflight: threading.Event | None = None
        # A waiter must never outlive the fetch it is waiting on. The fetcher already
        # has its own timeout; this is that plus a margin, so a wedged fetcher costs a
        # waiter one bounded wait and then the normal empty-cache path.
        self._wait_timeout = timeout_seconds + 1.0

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
            # The cause carries the detail (url, transport error) for the log; the
            # message deliberately carries none, because it reaches a caller.
            raise JWKSUnavailable("Could not load signing keys") from self._last_error
        return key

    def _floor(self) -> float:
        """Holding keys, the floor is a shield: a made-up kid must not buy an outbound
        fetch per request. Holding none, there is nothing to shield — every request is
        failing already — and the floor only strands the process, so it shrinks to the
        one job left: not stampeding an identity that is coming back up.

        _fetch_into_cache rebinds _cache outside the lock, so this can read the value
        from just before a successful fetch. It only ever goes empty to populated, so
        the stale read costs at most one extra fetch and never the reverse."""
        return self._min_refresh_interval if self._cache else self._cold_retry_interval

    def _maybe_refresh(self, now: float) -> None:
        with self._lock:
            inflight = self._inflight
            if inflight is not None:
                # Someone is already fetching. The refresh floor must not be read as
                # "a fetch has happened" — it hasn't finished yet, and returning here
                # would hand this caller an empty cache and a spurious 401.
                mine = False
            elif now - self._last_attempt_at < self._floor():
                return
            else:
                self._last_attempt_at = now
                inflight = self._inflight = threading.Event()
                mine = True

        if not mine:
            inflight.wait(self._wait_timeout)
            return

        try:
            self._fetch_into_cache()
        finally:
            # Cleared and signalled only after the cache (or _last_error) is written.
            # Signalling first would wake waiters onto exactly the empty cache this
            # whole mechanism exists to prevent.
            with self._lock:
                self._inflight = None
            inflight.set()

    def _fetch_into_cache(self) -> None:
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

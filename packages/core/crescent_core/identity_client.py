import threading
import time
from typing import Callable
import httpx

HTTP_TIMEOUT = 10.0
TOKEN_EXPIRY_SKEW_SECONDS = 30
# Identity rejects a larger id batch with a 422.
MAX_LOOKUP_IDS = 200

class IdentityUnavailable(Exception):
    """Couldn't reach identity, authenticate, or get a usable answer. Never means
    "no such user" — absence of an answer is not a verdict."""

class ServiceTokenClient:

    def __init__(self, base_url: str, client_id: str, client_secret: str, timeout_seconds: float = HTTP_TIMEOUT, poster: Callable[..., httpx.Response] | None = None):
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds
        self._poster = poster or self._http_poster
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._client_secret)

    def _http_poster(self, url: str, json: dict, headers: dict | None = None) -> httpx.Response:
        return httpx.post(url, json=json, headers=headers or {}, timeout=self._timeout)

    def _fetch_token(self) -> str:
        try:
            resp = self._poster(
                f"{self._base_url}/oauth/token",
                {
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                None,
            )
        except httpx.HTTPError as e:
            raise IdentityUnavailable(f"Could not reach identity for a service token: {e}") from e
        if resp.status_code >= 400:
            raise IdentityUnavailable(f"Identity rejected the service credentials (HTTP {resp.status_code})")
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise IdentityUnavailable("Identity returned no access_token")
        # Fall back to a short life if expires_in is missing, so a bad response can't
        # pin a stale token forever.
        expires_in = int(body.get("expires_in") or 60)
        self._token = token
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_EXPIRY_SKEW_SECONDS, 0)
        return token

    def token(self, force_refresh: bool = False) -> str:
        with self._lock:
            if force_refresh or self._token is None or time.monotonic() >= self._token_expires_at:
                return self._fetch_token()
            return self._token

    def lookup(self, path: str, user_ids: list[int]) -> dict:
        if len(user_ids) > MAX_LOOKUP_IDS:
            raise ValueError(f"At most {MAX_LOOKUP_IDS} ids per lookup")
        if not self.configured:
            raise IdentityUnavailable("No service client secret configured; cannot call identity")
        url = f"{self._base_url}{path}"
        payload = {"user_ids": list(user_ids)}
        try:
            token = self.token()
            resp = self._poster(url, payload, {"Authorization": f"Bearer {token}"})
            if resp.status_code == 401:
                token = self.token(force_refresh=True)
                resp = self._poster(url, payload, {"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise IdentityUnavailable(f"Could not reach identity for {path}: {e}") from e
        if resp.status_code >= 400:
            raise IdentityUnavailable(f"Identity lookup {path} failed (HTTP {resp.status_code})")
        try:
            return resp.json()
        except ValueError as e:
            raise IdentityUnavailable(f"Identity lookup {path} returned an unreadable body: {e}") from e

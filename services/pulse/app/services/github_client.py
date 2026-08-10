import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')

def _next_link(link_header: str) -> str | None:
    m = _NEXT_RE.search(link_header or "")
    return m.group(1) if m else None

def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

class GitHubRateLimited(Exception):

    def __init__(self, wait_seconds: float, url: str):
        self.wait_seconds = max(0.0, wait_seconds)
        self.resume_at = datetime.now(timezone.utc) + timedelta(seconds=self.wait_seconds)
        super().__init__(
            f"GitHub rate limit hit on {url}; retry in ~{round(self.wait_seconds / 60)} min "
            f"(resets at {self.resume_at.isoformat(timespec='seconds')})"
        )

class GitHubClient:
    _MAX_RETRIES = 3

    def __init__(self, token: str, base_url: str | None = None, sleep: Callable[[float], None] = time.sleep, max_wait_seconds: int = 60, transport: httpx.BaseTransport | None = None):
        self._base = (base_url or settings.GITHUB_API_URL).rstrip("/")
        self._sleep = sleep
        self._max_wait = max_wait_seconds
        self._http = httpx.Client(
            timeout=15.0,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        self._http.close()

    def _is_rate_limited(self, resp: httpx.Response) -> bool:
        if resp.status_code == 429:
            return True
        if resp.status_code == 403:
            return resp.headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in resp.headers
        return False

    def _wait_for(self, resp: httpx.Response) -> float:
        """How long GitHub says to wait, UNCAPPED — the raw number is what tells a
        few-second secondary-limit pause apart from an hour-long primary exhaustion."""
        if "Retry-After" in resp.headers:
            return max(0, int(resp.headers["Retry-After"]))
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
        return max(0, reset - int(time.time()))

    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        # Short waits are slept through; anything longer means the primary quota is gone
        # until GitHub's hourly reset, and sleeping through that would pin a worker for
        # the best part of an hour.
        for attempt in range(self._MAX_RETRIES + 1):
            resp = self._http.get(url, params=params)
            if not self._is_rate_limited(resp):
                resp.raise_for_status()
                return resp
            wait = self._wait_for(resp)
            if wait > self._max_wait or attempt == self._MAX_RETRIES:
                logger.warning("GitHub rate limit on %s: %ss to reset, giving up after %s attempt(s)", url, round(wait), attempt + 1)
                raise GitHubRateLimited(wait, url)
            self._sleep(min(self._max_wait, max(wait, 2 ** attempt)))

    def _paginate(self, path: str, params: dict | None = None, stop: Callable[[dict], bool] | None = None) -> list[dict]:
        params = {**(params or {})}
        params.setdefault("per_page", 100)
        url = f"{self._base}{path}"
        rows: list[dict] = []
        while url:
            resp = self._request(url, params=params)
            params = None
            for row in resp.json():
                if stop is not None and stop(row):
                    return rows
                rows.append(row)
            url = _next_link(resp.headers.get("Link", ""))
        return rows

    def get_repo(self, full_name: str) -> dict:
        return self._request(f"{self._base}/repos/{full_name}").json()

    def list_commits(self, full_name: str, since: str | None = None, sha: str | None = None) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/commits", {k: v for k, v in (("since", since), ("sha", sha)) if v})

    def list_branches(self, full_name: str) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/branches")

    def list_pull_requests(self, full_name: str, since: datetime | None = None) -> list[dict]:
        # /pulls has no `since` param, but sorted updated-desc lets us stop early.
        stop = None
        if since is not None:
            def stop(pr: dict) -> bool:
                updated = _parse_dt(pr.get("updated_at"))
                return updated is not None and updated < since
        return self._paginate(f"/repos/{full_name}/pulls", {"state": "all", "sort": "updated", "direction": "desc"}, stop=stop)

    def list_reviews(self, full_name: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/pulls/{number}/reviews")

    def list_issues(self, full_name: str, since: str | None = None) -> list[dict]:
        params = {"state": "all"}
        if since:
            params["since"] = since
        return self._paginate(f"/repos/{full_name}/issues", params)

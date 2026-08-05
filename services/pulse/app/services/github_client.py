"""A thin GitHub REST client for the sync engine.

Handles pagination and rate limits

`sleep` is injectable and every call goes through one httpx client, so tests drive
it with `httpx.MockTransport` — no real network and no real waits.
"""

import re
import time
from datetime import datetime
from typing import Callable
import httpx
from app.config import settings

_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')

def _next_link(link_header: str) -> str | None:
    m = _NEXT_RE.search(link_header or "")
    return m.group(1) if m else None

def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

class GitHubClient:
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
            # primary = quota exhausted; secondary = abuse detection, carries Retry-After
            return resp.headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in resp.headers
        return False

    def _wait_for(self, resp: httpx.Response) -> float:
        if "Retry-After" in resp.headers:
            return min(self._max_wait, int(resp.headers["Retry-After"]))
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
        return max(0, min(self._max_wait, reset - int(time.time())))

    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        # At most one wait-and-retry: enough to ride out one rate-limit window
        # without looping forever if something is genuinely wrong.
        for _ in range(2):
            resp = self._http.get(url, params=params)
            if self._is_rate_limited(resp):
                self._sleep(self._wait_for(resp))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def _paginate(self, path: str, params: dict | None = None, stop: Callable[[dict], bool] | None = None) -> list[dict]:
        params = {**(params or {})}
        params.setdefault("per_page", 100)
        url = f"{self._base}{path}"
        rows: list[dict] = []
        while url:
            resp = self._request(url, params=params)
            params = None  # the next-page URL already carries the query
            for row in resp.json():
                if stop is not None and stop(row):
                    return rows  # newest-first → everything past here is older
                rows.append(row)
            url = _next_link(resp.headers.get("Link", ""))
        return rows

    # ── the calls the sync engine needs ────────────────────────────────────────
    def get_repo(self, full_name: str) -> dict:
        return self._request(f"{self._base}/repos/{full_name}").json()

    def list_commits(self, full_name: str, since: str | None = None) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/commits", {"since": since} if since else {})

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

"""A thin GitHub REST client for the sync engine.

Handles the two things the plan calls out — pagination and rate limits — so the
sync service can stay about *what* to pull, not *how*:

- **Pagination:** follows the `Link: rel="next"` header until there are no pages.
- **Rate limits:** on a 403 with `X-RateLimit-Remaining: 0` (or a 429), waits until
  the reset time (capped) and retries once, rather than hammering GitHub.

`sleep` is injectable and every network call goes through one httpx client, so
tests can drive it with `httpx.MockTransport` without real network or real waits.
"""
import re
import time
from typing import Callable
import httpx
from app.config import settings

_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _next_link(link_header: str) -> str | None:
    """Pull the rel="next" URL out of a GitHub Link header, or None if last page."""
    m = _NEXT_RE.search(link_header or "")
    return m.group(1) if m else None


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

    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        # At most one wait-and-retry: enough to ride out a single rate-limit window
        # without looping forever if something is genuinely wrong.
        for _ in range(2):
            resp = self._http.get(url, params=params)
            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                self._sleep(self._wait_for(resp))
                continue
            if resp.status_code == 429:
                self._sleep(min(self._max_wait, int(resp.headers.get("Retry-After", "1"))))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def _wait_for(self, resp: httpx.Response) -> float:
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
        return max(0, min(self._max_wait, reset - int(time.time())))

    def _paginate(self, path: str, params: dict | None = None) -> list[dict]:
        params = {**(params or {})}
        params.setdefault("per_page", 100)
        url = f"{self._base}{path}"
        rows: list[dict] = []
        while url:
            resp = self._request(url, params=params)
            params = None  # the next-page URL already carries the query
            rows.extend(resp.json())
            url = _next_link(resp.headers.get("Link", ""))
        return rows

    # ── the calls the sync engine needs ────────────────────────────────────────
    def get_repo(self, full_name: str) -> dict:
        return self._request(f"{self._base}/repos/{full_name}").json()

    def list_commits(self, full_name: str, since: str | None = None) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/commits", {"since": since} if since else {})

    def list_pull_requests(self, full_name: str) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/pulls", {"state": "all", "sort": "updated", "direction": "desc"})

    def list_reviews(self, full_name: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/pulls/{number}/reviews")

    def list_issues(self, full_name: str, since: str | None = None) -> list[dict]:
        params = {"state": "all"}
        if since:
            params["since"] = since
        return self._paginate(f"/repos/{full_name}/issues", params)

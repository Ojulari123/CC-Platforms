from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sqlalchemy import func, select
from app import crypto
from app.config import settings
from app.models import Commit, GitHubAccount, Repository
from app.services import sync as sync_service
from app.services.github_client import GitHubClient

NOW = datetime.now(timezone.utc)

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _commit(sha: str, dated: datetime, login: str = "ada") -> dict:
    return {"sha": sha, "html_url": f"u/{sha}", "author": {"login": login},
            "commit": {"message": sha, "committer": {"date": _iso(dated)}}}

class FakeGitHub:
    def __init__(self):
        self.branches: dict[str, list[dict]] = {"main": [_commit("base", NOW - timedelta(days=1))]}
        self.pushed_at = _iso(NOW)
        self.prs: list[dict] = []
        self.issues: list[dict] = []
        self.calls: list[str] = []
        self.commit_call_at: datetime | None = None

    def push(self, branch: str, sha: str, dated: datetime) -> None:
        self.branches.setdefault(branch, []).insert(0, _commit(sha, dated))
        self.pushed_at = _iso(datetime.now(timezone.utc))

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        self.calls.append(f"{path}?{params}" if params else path)
        if path == "/repos/org/alpha":
            return httpx.Response(200, json={"id": 555, "name": "alpha", "full_name": "org/alpha",
                                             "private": False, "default_branch": "main",
                                             "owner": {"login": "org"}, "pushed_at": self.pushed_at})
        if path == "/repos/org/alpha/branches":
            return httpx.Response(200, json=[{"name": n, "commit": {"sha": rows[0]["sha"]}}
                                             for n, rows in self.branches.items() if rows])
        if path == "/repos/org/alpha/commits":
            self.commit_call_at = datetime.now(timezone.utc)
            rows = self.branches.get(params.get("sha") or "main", [])
            since = params.get("since")
            if since:
                cut = datetime.fromisoformat(since.replace("Z", "+00:00"))
                rows = [c for c in rows
                        if datetime.fromisoformat(c["commit"]["committer"]["date"].replace("Z", "+00:00")) >= cut]
            return httpx.Response(200, json=rows)
        if path == "/repos/org/alpha/pulls":
            return httpx.Response(200, json=self.prs)
        if path.startswith("/repos/org/alpha/pulls/"):
            return httpx.Response(200, json=[])
        if path == "/repos/org/alpha/issues":
            return httpx.Response(200, json=self.issues)
        raise AssertionError(f"unexpected GitHub call: {path}")

@pytest.fixture
def gh(db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPOS", "org/alpha")
    db.add(GitHubAccount(user_id=10, github_user_id=99, github_login="ada",
                         access_token_encrypted=crypto.encrypt("tok")))
    db.commit()
    return FakeGitHub()

def _sync(db, server):
    def make(token):
        return GitHubClient(token, base_url="https://api.github.test",
                            transport=httpx.MockTransport(server.handler))

    runs = sync_service.run_full_sync(db, make_client=make)
    assert runs[-1].status == "success", runs[-1].detail
    return runs[-1]

def _shas(db):
    return sorted(s for (s,) in db.execute(select(Commit.sha)))

def _commit_calls(server):
    return [c for c in server.calls if c.startswith("/repos/org/alpha/commits")]

def test_a_commit_dated_before_the_cursor_but_pushed_after_it_is_still_fetched(gh, db):
    _sync(db, gh)
    assert _shas(db) == ["base"]

    gh.push("main", "offline", NOW - timedelta(days=2))
    _sync(db, gh)

    assert _shas(db) == ["base", "offline"]

def test_with_no_overlap_that_commit_is_lost_for_good(gh, db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_SYNC_OVERLAP_MINUTES", 0)
    _sync(db, gh)
    gh.push("main", "offline", NOW - timedelta(days=2))

    for _ in range(3):
        _sync(db, gh)

    assert _shas(db) == ["base"]

def test_the_window_reaches_back_exactly_as_far_as_configured(gh, db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_SYNC_OVERLAP_MINUTES", 60)
    _sync(db, gh)
    gh.push("main", "just-inside", NOW - timedelta(minutes=30))
    gh.push("main", "too-old", NOW - timedelta(minutes=120))
    _sync(db, gh)

    assert _shas(db) == ["base", "just-inside"]

def test_the_cursor_is_stamped_before_the_fetch_not_after(gh, db):
    _sync(db, gh)
    repo = db.scalar(select(Repository).where(Repository.full_name == "org/alpha"))
    assert sync_service._as_utc(repo.last_synced_at) <= gh.commit_call_at

def test_commits_on_other_branches_are_synced(gh, db):
    _sync(db, gh)
    gh.push("feature", "feat1", NOW)
    _sync(db, gh)

    assert _shas(db) == ["base", "feat1"]
    assert [c for c in gh.calls if "sha=feature" in c and "since=" in c]

def test_a_branch_pointing_at_a_commit_from_this_same_pass_costs_no_call(gh, db):
    gh.branches["release"] = list(gh.branches["main"])
    _sync(db, gh)

    assert "sha=release" not in " ".join(gh.calls)

def test_a_branch_whose_head_we_already_hold_costs_no_call(gh, db):
    gh.push("feature", "feat1", NOW)
    _sync(db, gh)
    gh.calls.clear()
    _sync(db, gh)

    assert len(_commit_calls(gh)) == 1
    assert any(c.startswith("/repos/org/alpha/branches") for c in gh.calls)
    assert "sha=" not in " ".join(gh.calls)

def test_branch_coverage_can_be_turned_off(gh, db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_SYNC_BRANCHES", False)
    gh.push("feature", "feat1", NOW)
    run = _sync(db, gh)

    assert _shas(db) == ["base"]
    assert not any(c.startswith("/repos/org/alpha/branches") for c in gh.calls)
    assert "branches=0" in run.detail

def test_the_number_of_branches_touched_per_pass_is_capped(gh, db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_SYNC_MAX_BRANCHES", 2)
    for i in range(5):
        gh.push(f"feature-{i}", f"feat{i}", NOW)
    run = _sync(db, gh)

    assert len([c for c in gh.calls if "sha=feature" in c]) == 2
    assert "branches=2" in run.detail

def test_a_repo_with_no_push_since_the_window_skips_the_commit_and_branch_calls(gh, db):
    gh.push("feature", "feat1", NOW)
    _sync(db, gh)
    gh.pushed_at = _iso(NOW - timedelta(days=30))
    gh.calls.clear()
    _sync(db, gh)

    assert _commit_calls(gh) == []
    assert [c.split("?")[0] for c in gh.calls] == ["/repos/org/alpha", "/repos/org/alpha/pulls", "/repos/org/alpha/issues"]

def test_the_pushed_at_skip_never_skips_pull_requests_or_issues(gh, db):
    _sync(db, gh)
    gh.pushed_at = _iso(NOW - timedelta(days=30))
    gh.issues = [{"id": 22, "number": 3, "title": "a bug", "state": "open",
                  "created_at": _iso(NOW), "closed_at": None, "user": {"login": "ada"}, "html_url": "u"}]
    gh.calls.clear()
    run = _sync(db, gh)

    assert "issues=1" in run.detail
    assert any(c.startswith("/repos/org/alpha/issues") for c in gh.calls)

def test_refetching_the_window_neither_duplicates_rows_nor_reattributes_them(gh, db):
    _sync(db, gh)
    gh.push("main", "again", NOW)
    _sync(db, gh)
    assert db.scalar(select(func.count()).select_from(Commit)) == 2
    assert {c.author_user_id for c in db.scalars(select(Commit))} == {10}

    db.query(GitHubAccount).delete()
    db.commit()
    db.add(GitHubAccount(user_id=11, github_user_id=1, github_login="bob",
                         access_token_encrypted=crypto.encrypt("tok")))
    db.commit()
    _sync(db, gh)

    assert db.scalar(select(func.count()).select_from(Commit)) == 2
    assert {c.author_user_id for c in db.scalars(select(Commit))} == {10}

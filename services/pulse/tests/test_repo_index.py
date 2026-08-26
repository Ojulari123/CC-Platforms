import base64
import threading
import time
from datetime import datetime, timezone
import httpx
import pytest
from app import crypto
from app.config import settings
from app.models import (
    INDEX_ERROR, INDEX_PAUSED, INDEX_PENDING, INDEX_RATE_LIMITED, INDEX_READY, LLM_KIND_EMBEDDING,
    PROVIDER_OPENAI, SCOPE_DEPARTMENT, SCOPE_USER,
    ApiCredential, GitHubAccount, IndexedRepo, LlmUsage, RepoChunk, Repository, TokenBudget,
)
from app.services import embeddings, llm_budget, repo_index
from app.services.github_client import GitHubClient, GitHubRateLimited
from app.services.llm_budget import BudgetExceededError
from app.services.provider_limits import ProviderRateLimited
from app.services.repo_index import NO_ACCOUNT_DETAIL, RECONNECT_DETAIL

OWNER = 10
OTHER = 11

CALLER = dict(user_id=OWNER, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])
STRANGER = dict(user_id=OTHER, memberships=[{"dept_id": 1, "team_id": None, "role": "engineer"}])

HEAD_SHA = "a" * 40


def _seed_account(db, user_id=OWNER, scopes="read:user,repo"):
    account = GitHubAccount(
        user_id=user_id, github_user_id=1000 + user_id, github_login=f"dev{user_id}",
        access_token_encrypted=crypto.encrypt("gho_token"), scopes=scopes,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _seed_row(db, *, full_name="org/alpha", owner=OWNER, is_public=True, status=INDEX_PENDING):
    row = IndexedRepo(full_name=full_name, owner_user_id=owner, is_public=is_public, status=status)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _tree(paths_and_sizes, truncated=False):
    return {
        "sha": "t" * 40,
        "truncated": truncated,
        "tree": [{"type": "blob", "path": p, "sha": f"blob-{p}", "size": s} for p, s in paths_and_sizes],
    }


class FakeClient:
    """Stands in for GitHubClient at the same seam sync.py uses (`make_client`), so no
    test ever needs an outbound request — the suite blocks those outright."""

    def __init__(self, tree, blobs, *, default_branch="main", raises=None):
        self._tree = tree
        self._blobs = blobs
        self._default_branch = default_branch
        self._raises = raises
        self.closed = False
        self.token = None
        self.blob_calls: list[str] = []

    def get_repo(self, full_name):
        if self._raises is not None:
            raise self._raises
        return {"full_name": full_name, "default_branch": self._default_branch}

    def get_commit(self, full_name, ref):
        return {"sha": HEAD_SHA, "ref": ref}

    def get_tree(self, full_name, ref):
        return self._tree

    def get_blob(self, full_name, sha):
        self.blob_calls.append(sha)
        return self._blobs[sha]

    def close(self):
        self.closed = True


def _maker(client):
    def make(token):
        client.token = token
        return client
    return make


@pytest.fixture
def fake_embeddings(monkeypatch):
    """One deterministic vector per text: length-3, so the assertions can be read."""
    rec = {"texts": [], "calls": 0, "credential": None}

    def embed(texts, credential=None):
        rec["calls"] += 1
        rec["texts"] = list(texts)
        rec["credential"] = credential
        return [[float(len(t)), 1.0, 0.0] for t in texts], 7 * len(texts)

    monkeypatch.setattr(embeddings, "embed_texts", embed)
    return rec


@pytest.fixture
def queued(monkeypatch):
    """Celery has no broker in tests; record the enqueue instead of attempting it."""
    from app.tasks import index_repo

    ids: list[int] = []
    monkeypatch.setattr(index_repo, "delay", lambda indexed_repo_id: ids.append(indexed_repo_id))
    return ids


class TestFullNameValidation:

    @pytest.mark.parametrize("value", [
        "", "alpha", "org/alpha/extra", "org//alpha", "-org/alpha", "org/alpha?x=1",
        "../../etc/passwd", "org/..", "../alpha", "org/.", ".", "..",
        "org/alpha%2F..", "org alpha/beta", "org/alpha#frag", "https://github.com/org/alpha",
    ])
    def test_junk_and_traversal_are_refused(self, value):
        assert repo_index.is_valid_full_name(value) is False

    @pytest.mark.parametrize("value", ["org/alpha", "Cypher-Crescent/cc-platforms", "a/b", "org/some.repo_name-2"])
    def test_real_names_are_accepted(self, value):
        assert repo_index.is_valid_full_name(value) is True

    def test_the_api_refuses_a_traversal_body(self, client, act_as, queued):
        act_as(**CALLER)

        r = client.post("/chat/repos", json={"full_name": "../../etc/passwd"})

        assert r.status_code == 422
        assert queued == []

    def test_the_service_refuses_a_traversal_even_without_the_schema(self, db, act_as):
        user = act_as(**CALLER)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            repo_index.request_public_index(db, user, "org/..")

        assert exc.value.status_code == 422


class TestPathAndSizeFilters:

    @pytest.mark.parametrize("path", [
        "node_modules/left-pad/index.js", "src/.git/config", "dist/app.js", "build/out.py",
        "vendor/lib.go", "app/__pycache__/x.pyc", ".venv/lib/x.py", "venv/lib/x.py",
        "target/debug/x.rs", ".next/build.js", ".nuxt/app.js", "coverage/lcov.info",
    ])
    def test_generated_directories_are_excluded(self, path):
        assert repo_index.is_indexable_path(path) is False

    @pytest.mark.parametrize("path", [
        "docs/logo.png", "static/hero.jpg", "media/clip.mp4", "audio/theme.mp3",
        "fonts/inter.woff2", "release/bundle.zip", "app/mod.pyc", "bin/tool.exe",
        "poetry.lock", "static/app.min.js", "static/app.min.css", "dist.map",
    ])
    def test_binary_and_generated_files_are_excluded(self, path):
        assert repo_index.is_indexable_path(path) is False

    @pytest.mark.parametrize("path", [
        "README.md", "app/main.py", ".gitignore", "src/index.ts", "Makefile", "a/b/c.vue",
    ])
    def test_source_and_dotfiles_are_kept(self, path):
        assert repo_index.is_indexable_path(path) is True

    def test_an_oversized_blob_is_dropped(self, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_MAX_FILE_BYTES", 100)

        picked, oversize, over_cap = repo_index._select_blobs(
            _tree([("a.py", 10), ("big.py", 5000)])["tree"]
        )

        assert [p["path"] for p in picked] == ["a.py"]
        assert oversize == 1 and over_cap == 0

    def test_the_file_cap_reports_what_it_left_behind(self, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_MAX_FILES", 2)

        picked, _, over_cap = repo_index._select_blobs(
            _tree([("a.py", 1), ("b.py", 1), ("c.py", 1), ("d.py", 1)])["tree"]
        )

        assert len(picked) == 2 and over_cap == 2

    def test_trees_and_commits_in_the_tree_are_not_files(self):
        nodes = [{"type": "tree", "path": "app", "sha": "t1"}, {"type": "commit", "path": "sub", "sha": "c1"}]

        picked, _, _ = repo_index._select_blobs(nodes)

        assert picked == []


class TestChunking:

    def test_line_numbers_are_one_indexed_and_inclusive(self):
        text = "\n".join(f"line{i}" for i in range(1, 11))

        windows = repo_index.chunk_lines(text, size=4, overlap=1)

        assert [(s, e) for s, e, _ in windows] == [(1, 4), (4, 7), (7, 10)]
        assert windows[0][2].splitlines()[0] == "line1"
        assert windows[0][2].splitlines()[-1] == "line4"

    def test_windows_overlap_so_a_boundary_straddler_stays_whole(self):
        text = "\n".join(f"line{i}" for i in range(1, 21))

        windows = repo_index.chunk_lines(text, size=10, overlap=4)

        assert windows[0][1] >= windows[1][0], "windows must share lines, not just touch"
        shared = set(range(windows[1][0], windows[0][1] + 1))
        assert len(shared) == 4

    def test_a_file_shorter_than_one_window_is_a_single_chunk(self):
        windows = repo_index.chunk_lines("a\nb\nc", size=60, overlap=10)

        assert windows == [(1, 3, "a\nb\nc")]

    def test_an_empty_file_produces_nothing(self):
        assert repo_index.chunk_lines("", size=60, overlap=10) == []

    def test_an_overlap_at_or_above_the_window_still_advances(self):
        windows = repo_index.chunk_lines("a\nb\nc\nd", size=2, overlap=5)

        assert [(s, e) for s, e, _ in windows] == [(1, 2), (2, 3), (3, 4)]

    def test_token_estimate_is_never_zero(self):
        assert repo_index.token_estimate("") == 1
        assert repo_index.token_estimate("x" * 400) == 100


class TestIngest:

    def _blobs(self, mapping):
        return {f"blob-{path}": body for path, body in mapping.items()}

    def test_a_clean_repo_indexes_to_ready(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("app/main.py", 20), ("README.md", 10)]),
                            self._blobs({"app/main.py": b"a\nb\nc", "README.md": b"hello"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert out.detail is None
        assert out.commit_sha == HEAD_SHA
        assert out.file_count == 2 and out.chunk_count == 2
        assert out.started_at is not None and out.finished_at is not None
        assert client.closed is True
        chunks = db.query(RepoChunk).filter_by(indexed_repo_id=row.id).all()
        assert sorted(c.path for c in chunks) == ["README.md", "app/main.py"]
        assert all(c.embedding is not None for c in chunks)

    def test_the_token_ledger_records_the_embedding_spend(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        usage = db.query(LlmUsage).all()
        assert len(usage) == 1
        assert usage[0].kind == LLM_KIND_EMBEDDING
        assert usage[0].report_id is None
        assert usage[0].user_id == OWNER
        assert usage[0].tokens == 7

    def test_filtered_paths_never_reach_a_blob_request(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([("app/main.py", 5), ("node_modules/x/index.js", 5), ("docs/logo.png", 5)])
        client = FakeClient(tree, self._blobs({"app/main.py": b"code"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert client.blob_calls == ["blob-app/main.py"]
        assert [c.path for c in db.query(RepoChunk).all()] == ["app/main.py"]

    def test_an_oversized_file_is_reported_in_detail(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_MAX_FILE_BYTES", 100)
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5), ("huge.csv", 900_000)]), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "1 file(s) were skipped for being larger than" in out.detail

    def test_the_file_cap_is_reported_in_detail(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_MAX_FILES", 1)
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5), ("b.py", 5)]), self._blobs({"a.py": b"x", "b.py": b"y"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "1 file(s) were left out" in out.detail
        assert out.file_count == 1

    def test_a_truncated_tree_is_recorded(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5)], truncated=True), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "incomplete file list" in out.detail

    def test_a_file_that_is_not_utf8_is_skipped_and_reported(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5), ("blob.dat2", 5)]),
                            self._blobs({"a.py": b"x", "blob.dat2": b"\xff\xfe\x00binary"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "not UTF-8 text" in out.detail
        assert out.file_count == 1

    def test_an_empty_file_adds_no_chunks(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("empty.py", 0), ("a.py", 5)]),
                            self._blobs({"empty.py": b"", "a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.file_count == 1 and out.chunk_count == 1

    def test_re_ingest_replaces_rather_than_appends(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        first = FakeClient(_tree([("a.py", 5), ("b.py", 5)]), self._blobs({"a.py": b"x", "b.py": b"y"}))
        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(first))
        assert db.query(RepoChunk).count() == 2

        second = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(second))

        assert out.chunk_count == 1
        assert [c.path for c in db.query(RepoChunk).all()] == ["a.py"]

    def test_rate_limiting_ends_as_rate_limited_with_a_wait(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient({}, {}, raises=GitHubRateLimited(30 * 60, "https://api.github.test/repos/org/alpha"))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_RATE_LIMITED
        assert "30 minute(s)" in out.detail
        assert out.finished_at is not None

    def test_an_unexpected_failure_never_leaks_exception_text(self, db, fake_embeddings):
        _seed_account(db)
        row = _seed_row(db)
        secret = "postgresql://admin:hunter2@db.internal/pulse"
        client = FakeClient({}, {}, raises=RuntimeError(secret))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert secret not in out.detail
        assert "hunter2" not in out.detail
        assert "reading the repository" in out.detail

    def test_an_embedding_outage_never_leaks_provider_text(self, db, monkeypatch):
        def boom(_texts, credential=None):
            raise embeddings.EmbeddingError("openai 500 from https://api.openai.com/v1/embeddings org-abc")

        monkeypatch.setattr(embeddings, "embed_texts", boom)
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert "api.openai.com" not in out.detail
        assert "unavailable right now" in out.detail

    def test_a_private_repo_without_a_connected_account_says_so(self, db, fake_embeddings):
        row = _seed_row(db, is_public=False)
        client = FakeClient(_tree([]), {})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert out.detail == NO_ACCOUNT_DETAIL

    def test_a_private_repo_without_the_repo_scope_asks_for_a_reconnect(self, db, fake_embeddings):
        _seed_account(db, scopes="read:user")
        row = _seed_row(db, is_public=False)
        client = FakeClient(_tree([]), {})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert out.detail == RECONNECT_DETAIL
        assert out.detail != NO_ACCOUNT_DETAIL

    def test_a_private_repo_with_the_scope_uses_the_owners_token(self, db, fake_embeddings):
        _seed_account(db, scopes="read:user,repo")
        row = _seed_row(db, is_public=False)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert client.token == "gho_token"

    def test_a_public_repo_falls_back_to_no_token(self, db, fake_embeddings):
        row = _seed_row(db, is_public=True)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert client.token is None

    def test_a_public_repo_prefers_the_owners_token_when_there_is_one(self, db, fake_embeddings):
        _seed_account(db, scopes="read:user")
        row = _seed_row(db, is_public=True)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert client.token == "gho_token"

    def test_a_stored_row_with_a_bad_name_is_refused_before_any_request(self, db, fake_embeddings):
        row = _seed_row(db, full_name="org/..")
        client = FakeClient(_tree([]), {})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert "owner/name" in out.detail
        assert client.blob_calls == []

    def test_a_missing_row_is_a_programming_error_not_a_status(self, db):
        with pytest.raises(LookupError):
            repo_index.ingest_repo(db, indexed_repo_id=999)

    def test_the_daily_cap_stops_the_worker_too(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=100))
        db.commit()
        _seed_account(db)
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}))

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert "used today's AI allowance" in out.detail
        assert fake_embeddings["calls"] == 0

    def test_a_repo_with_no_default_branch_still_resolves(self, db, fake_embeddings):
        row = _seed_row(db)
        client = FakeClient(_tree([("a.py", 5)]), self._blobs({"a.py": b"x"}), default_branch=None)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY


class TestSearchChunks:

    def _seed_chunks(self, db, row_id, vectors):
        for i, vector in enumerate(vectors):
            db.add(RepoChunk(
                indexed_repo_id=row_id, path=f"f{i}.py", start_line=1, end_line=1,
                content=f"body {i}", token_estimate=1,
                embedding=repo_index._encode_vector(db, vector),
            ))
        db.commit()

    def test_ranking_is_by_cosine_similarity(self, db):
        row = _seed_row(db)
        # f0 points away from the query, f1 is orthogonal, f2 is the query itself.
        self._seed_chunks(db, row.id, [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])

        hits = repo_index.search_chunks(db, indexed_repo_id=row.id, query_vector=[1.0, 0.0, 0.0], k=3)

        assert [h.path for h in hits] == ["f2.py", "f1.py", "f0.py"]

    def test_k_limits_the_result(self, db):
        row = _seed_row(db)
        self._seed_chunks(db, row.id, [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 0.0, 1.0]])

        hits = repo_index.search_chunks(db, indexed_repo_id=row.id, query_vector=[1.0, 0.0, 0.0], k=2)

        assert [h.path for h in hits] == ["f0.py", "f1.py"]

    def test_another_repos_chunks_are_never_returned(self, db):
        mine = _seed_row(db, full_name="org/alpha")
        theirs = _seed_row(db, full_name="org/beta")
        self._seed_chunks(db, theirs.id, [[1.0, 0.0, 0.0]])

        assert repo_index.search_chunks(db, indexed_repo_id=mine.id, query_vector=[1.0, 0.0, 0.0], k=5) == []

    def test_a_vector_survives_the_sqlite_round_trip(self, db):
        row = _seed_row(db)
        self._seed_chunks(db, row.id, [[0.25, -0.5, 0.75]])

        stored = db.query(RepoChunk).one()

        assert repo_index._decode_vector(stored.embedding) == pytest.approx([0.25, -0.5, 0.75])

    def test_a_zero_vector_ranks_last_rather_than_raising(self, db):
        row = _seed_row(db)
        self._seed_chunks(db, row.id, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

        hits = repo_index.search_chunks(db, indexed_repo_id=row.id, query_vector=[1.0, 0.0, 0.0], k=2)

        assert [h.path for h in hits] == ["f1.py", "f0.py"]


class TestRoutes:

    ENDPOINTS = [
        ("get", "/chat/repos", None),
        ("post", "/chat/repos", {"full_name": "org/alpha"}),
        ("post", "/chat/repos/mine", None),
        ("get", "/chat/repos/1", None),
        ("delete", "/chat/repos/1", None),
        ("get", "/chat/repos/github-status", None),
    ]

    @pytest.mark.parametrize("method,path,body", ENDPOINTS)
    def test_every_endpoint_needs_a_token(self, client, method, path, body):
        call = getattr(client, method)
        r = call(path, json=body) if body is not None else call(path)

        assert r.status_code == 401

    def test_literal_segments_are_not_parsed_as_ids(self, client, act_as, db):
        act_as(**CALLER)

        assert client.get("/chat/repos/github-status").status_code == 200

    def test_github_status_reports_connection_and_scope(self, client, act_as, db):
        act_as(**CALLER)
        assert client.get("/chat/repos/github-status").json() == {
            "connected": False, "has_repo_scope": False, "reconnect_required": False, "detail": None,
        }

        # An account connected before the scopes were widened: connected, but its token
        # cannot read private repositories and never will until it is reconnected.
        _seed_account(db, scopes="read:user")
        assert client.get("/chat/repos/github-status").json() == {
            "connected": True, "has_repo_scope": False, "reconnect_required": True,
            "detail": RECONNECT_DETAIL,
        }

        db.query(GitHubAccount).delete()
        db.commit()
        _seed_account(db, scopes="read:user,repo")
        assert client.get("/chat/repos/github-status").json() == {
            "connected": True, "has_repo_scope": True, "reconnect_required": False, "detail": None,
        }

    def test_a_public_repo_is_queued_and_enqueued(self, client, act_as, db, queued):
        act_as(**CALLER)

        r = client.post("/chat/repos", json={"full_name": "org/alpha"})

        assert r.status_code == 202
        body = r.json()
        assert body["full_name"] == "org/alpha" and body["status"] == INDEX_PENDING
        assert body["is_public"] is True and body["owner_user_id"] == OWNER
        assert queued == [body["id"]]

    def test_a_tracked_private_repo_is_queued_as_private(self, client, act_as, db, queued):
        db.add(Repository(github_repo_id=1, full_name="org/secret", owner="org", name="secret", private=True))
        db.commit()
        act_as(**CALLER)

        r = client.post("/chat/repos", json={"full_name": "org/secret"})

        assert r.status_code == 202
        assert r.json()["is_public"] is False
        assert r.json()["repo_id"] is not None

    def test_asking_twice_reuses_the_row(self, client, act_as, db, queued):
        act_as(**CALLER)
        first = client.post("/chat/repos", json={"full_name": "org/alpha"}).json()
        _seed_chunks_marker = db.query(IndexedRepo).count()

        second = client.post("/chat/repos", json={"full_name": "org/alpha"}).json()

        assert second["id"] == first["id"]
        assert _seed_chunks_marker == 1 and db.query(IndexedRepo).count() == 1

    def test_the_list_shows_only_the_callers_own(self, client, act_as, db):
        _seed_row(db, full_name="org/mine", owner=OWNER)
        _seed_row(db, full_name="org/theirs", owner=OTHER)
        act_as(**CALLER)

        body = client.get("/chat/repos").json()

        assert body["total"] == 1
        assert [i["full_name"] for i in body["items"]] == ["org/mine"]

    def test_someone_elses_index_is_a_404_not_a_403(self, client, act_as, db):
        theirs = _seed_row(db, full_name="org/theirs", owner=OTHER)
        act_as(**STRANGER)
        assert client.get(f"/chat/repos/{theirs.id}").status_code == 200

        act_as(**CALLER)
        assert client.get(f"/chat/repos/{theirs.id}").status_code == 404
        assert client.delete(f"/chat/repos/{theirs.id}").status_code == 404
        assert db.query(IndexedRepo).count() == 1

    def test_a_missing_index_is_a_404(self, client, act_as):
        act_as(**CALLER)

        assert client.get("/chat/repos/4242").status_code == 404

    def test_deleting_removes_the_row_and_its_chunks(self, client, act_as, db):
        row = _seed_row(db)
        db.add(RepoChunk(indexed_repo_id=row.id, path="a.py", start_line=1, end_line=1, content="x", token_estimate=1))
        db.commit()
        act_as(**CALLER)

        assert client.delete(f"/chat/repos/{row.id}").status_code == 204
        assert db.query(IndexedRepo).count() == 0
        assert db.query(RepoChunk).count() == 0

    def test_the_daily_cap_answers_429_with_a_reset_time(self, client, act_as, db, monkeypatch, queued):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 50)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=50))
        db.commit()
        act_as(**CALLER)

        r = client.post("/chat/repos", json={"full_name": "org/alpha"})

        assert r.status_code == 429
        assert "resets at" in r.json()["detail"]
        assert queued == []

    def test_a_cap_of_zero_lets_a_heavy_user_through(self, client, act_as, db, monkeypatch, queued):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=9_000_000))
        db.commit()
        act_as(**CALLER)

        assert client.post("/chat/repos", json={"full_name": "org/alpha"}).status_code == 202


class TestMyRepos:

    def test_without_a_connected_account_it_is_a_409(self, client, act_as, queued):
        act_as(**CALLER)

        r = client.post("/chat/repos/mine")

        assert r.status_code == 409
        assert "Connect your GitHub account" in r.json()["detail"]

    def test_without_the_repo_scope_it_asks_for_a_reconnect(self, client, act_as, db, queued):
        _seed_account(db, scopes="read:user")
        act_as(**CALLER)

        r = client.post("/chat/repos/mine")

        assert r.status_code == 409
        assert r.json()["detail"] == RECONNECT_DETAIL

    def test_discovered_repos_are_queued_with_their_visibility(self, db, act_as):
        _seed_account(db)
        user = act_as(**CALLER)
        found = [
            {"full_name": "org/alpha", "private": False},
            {"full_name": "org/secret", "private": True},
            {"full_name": "not a repo", "private": False},
        ]

        class Lister:
            def __init__(self):
                self.closed = False

            def list_repos_for_token(self):
                return found

            def close(self):
                self.closed = True

        lister = Lister()
        rows = repo_index.request_own_repos(db, user, make_client=lambda token: lister)

        assert [r.full_name for r in rows] == ["org/alpha", "org/secret"]
        assert [r.is_public for r in rows] == [True, False]
        assert all(r.status == INDEX_PENDING for r in rows)
        assert lister.closed is True

    def test_the_route_enqueues_one_task_per_discovered_repo(self, client, act_as, db, queued, monkeypatch):
        _seed_account(db)
        act_as(**CALLER)
        monkeypatch.setattr(
            repo_index, "request_own_repos",
            lambda _db, _user: [_seed_row(_db, full_name="org/alpha"), _seed_row(_db, full_name="org/beta")],
        )

        r = client.post("/chat/repos/mine")

        assert r.status_code == 202
        assert len(r.json()) == 2
        assert len(queued) == 2

    def test_the_daily_cap_stops_discovery(self, client, act_as, db, monkeypatch, queued):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 10)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=10))
        db.commit()
        _seed_account(db)
        act_as(**CALLER)

        assert client.post("/chat/repos/mine").status_code == 429


class TestGitHubClientContentReads:
    """The new content endpoints, against a mock transport — the suite blocks real HTTP."""

    def _client(self, handler):
        return GitHubClient("tok", base_url="https://api.github.test", sleep=lambda _s: None,
                            transport=httpx.MockTransport(handler))

    def test_a_blob_is_base64_decoded(self):
        def handler(request):
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(b"print(1)").decode()})

        assert self._client(handler).get_blob("org/alpha", "sha1") == b"print(1)"

    def test_an_unencoded_blob_is_passed_through(self):
        def handler(request):
            return httpx.Response(200, json={"encoding": "utf-8", "content": "plain"})

        assert self._client(handler).get_blob("org/alpha", "sha1") == b"plain"

    def test_the_tree_is_requested_recursively_and_keeps_its_truncated_flag(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"sha": "t1", "truncated": True, "tree": []})

        out = self._client(handler).get_tree("org/alpha", "main")

        assert out["truncated"] is True
        assert "recursive=1" in seen["url"] and "/git/trees/main" in seen["url"]

    def test_a_missing_readme_is_none_not_an_error(self):
        def handler(request):
            return httpx.Response(404, json={"message": "Not Found"})

        assert self._client(handler).get_readme("org/alpha") is None

    def test_a_readme_is_decoded_text(self):
        def handler(request):
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode("# Hi".encode()).decode()})

        assert self._client(handler).get_readme("org/alpha") == "# Hi"

    def test_a_readme_failure_other_than_404_still_raises(self):
        def handler(request):
            return httpx.Response(500, json={"message": "boom"})

        with pytest.raises(httpx.HTTPStatusError):
            self._client(handler).get_readme("org/alpha")

    def test_repos_for_a_token_include_org_and_collaborator_repos(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json=[{"full_name": "org/alpha"}])

        out = self._client(handler).list_repos_for_token()

        assert out == [{"full_name": "org/alpha"}]
        assert "organization_member" in seen["url"] and "collaborator" in seen["url"]

    def test_a_commit_pins_a_branch_to_a_sha(self):
        def handler(request):
            return httpx.Response(200, json={"sha": HEAD_SHA})

        assert self._client(handler).get_commit("org/alpha", "main")["sha"] == HEAD_SHA


class TestTask:

    def test_the_task_is_registered_without_a_new_schedule(self):
        from app.celery_app import celery

        assert "app.tasks.index_repo" in celery.tasks
        assert list(celery.conf.beat_schedule) == ["daily-github-sync"]

    def test_the_task_delegates_to_the_service_and_closes_its_session(self, monkeypatch, db):
        import app.tasks as tasks

        closed = {"n": 0}

        class Session:
            def close(self):
                closed["n"] += 1

        row = _seed_row(db, full_name="org/alpha", status=INDEX_READY)
        row.chunk_count = 3
        db.commit()

        monkeypatch.setattr(tasks, "SessionLocal", lambda: Session())
        monkeypatch.setattr(tasks.repo_index_service, "ingest_repo", lambda _db, *, indexed_repo_id: row)

        assert tasks.index_repo(row.id) == INDEX_READY
        assert closed["n"] == 1


class TestCredentialInTheWorker:
    """ingest_repo runs in Celery with no request token, so the key is resolved from the
    row's owner_user_id instead. That reaches their own key and the platform env key; a
    department key is out of reach here because department membership only ever arrives
    on a token."""

    def _store(self, db, owner, key="sk-mine-9999", provider=PROVIDER_OPENAI, bypass=False, dept=None, scope=SCOPE_USER):
        db.add(ApiCredential(scope=scope, owner_user_id=owner if scope == SCOPE_USER else None,
                             dept_id=dept, provider=provider, key_encrypted=crypto.encrypt(key),
                             last_four=key[-4:], bypass_token_cap=bypass, created_by_user_id=owner))
        db.commit()

    def _ingest(self, db, row=None):
        row = row or _seed_row(db)
        client = FakeClient(_tree([("app/main.py", 20)]), {"blob-app/main.py": b"a\nb\nc"})
        return repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

    def test_the_owners_own_key_is_what_the_worker_spends(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        _seed_account(db)
        self._store(db, OWNER)
        assert self._ingest(db).status == INDEX_READY
        credential = fake_embeddings["credential"]
        assert credential.source == "user"
        assert credential.key == "sk-mine-9999"

    def test_another_users_key_is_never_picked_up(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        _seed_account(db)
        self._store(db, OTHER, key="sk-theirs-1111")
        assert self._ingest(db).status == INDEX_READY
        assert fake_embeddings["credential"].source == "platform"

    def test_a_department_key_is_out_of_reach_without_a_token(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        _seed_account(db)
        self._store(db, OWNER, key="sk-dept-2222", scope=SCOPE_DEPARTMENT, dept=1)
        assert self._ingest(db).status == INDEX_READY
        assert fake_embeddings["credential"].source == "platform"

    def test_with_nothing_stored_the_platform_env_key_is_passed(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        _seed_account(db)
        assert self._ingest(db).status == INDEX_READY
        assert fake_embeddings["credential"].source == "platform"
        assert fake_embeddings["credential"].key == "sk-platform-0000"

    def test_a_bypassing_owner_key_indexes_past_the_daily_cap(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100)
        db.add(LlmUsage(kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=500))
        db.commit()
        _seed_account(db)
        row = _seed_row(db)
        assert self._ingest(db, row).status == INDEX_ERROR
        self._store(db, OWNER, bypass=True)
        assert self._ingest(db, row).status == INDEX_READY

    def test_the_platform_key_is_never_bypassable_in_the_worker(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100)
        db.add(LlmUsage(kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=500))
        db.commit()
        _seed_account(db)
        out = self._ingest(db)
        assert out.status == INDEX_ERROR
        assert "used today's AI allowance" in out.detail
        assert fake_embeddings["calls"] == 0


class _SlowClient(FakeClient):
    """Records how many blob requests were in flight at once, so the bound on the fetch
    pool is measured rather than assumed."""

    def __init__(self, *args, head=HEAD_SHA, **kwargs):
        super().__init__(*args, **kwargs)
        self._head = head
        self._lock = threading.Lock()
        self._live = 0
        self.peak = 0

    def get_commit(self, full_name, ref):
        return {"sha": self._head, "ref": ref}

    def get_blob(self, full_name, sha):
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
        try:
            time.sleep(0.02)
            return super().get_blob(full_name, sha)
        finally:
            with self._lock:
                self._live -= 1


class _FailingClient(FakeClient):
    """Fails on one named blob. Everything before it is already committed, which is what
    a resumed run is supposed to find."""

    def __init__(self, *args, fail_on=None, error=None, head=HEAD_SHA, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_on = fail_on
        self._error = error or GitHubRateLimited(120, "https://api.github.com/blob")
        self._head = head

    def get_commit(self, full_name, ref):
        return {"sha": self._head, "ref": ref}

    def get_blob(self, full_name, sha):
        if sha == self._fail_on:
            raise self._error
        return super().get_blob(full_name, sha)


class TestConcurrentFetch:

    def _repo(self, db, count):
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(count)]
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"line for {p}".encode() for p in paths}
        return row, tree, blobs

    def test_blobs_are_fetched_concurrently_up_to_the_cap(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 4)
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 12)
        row, tree, blobs = self._repo(db, 12)
        client = _SlowClient(tree, blobs)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY and out.file_count == 12
        assert client.peak > 1, "nothing ran in parallel"
        assert client.peak <= 4, f"the pool went past its cap: {client.peak}"

    def test_concurrency_of_one_fetches_serially(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 1)
        row, tree, blobs = self._repo(db, 6)
        client = _SlowClient(tree, blobs)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert client.peak == 1

    def test_every_chunk_keeps_the_path_its_bytes_came_from(self, db, fake_embeddings, monkeypatch):
        """Completion order is not request order once there is a pool, so this is the
        assertion that a vector cannot end up filed against the wrong file."""
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 6)
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(10)]
        client = _SlowClient(_tree([(p, 5) for p in paths]),
                             {f"blob-{p}": f"body of {p}".encode() for p in paths})

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        chunks = db.query(RepoChunk).filter_by(indexed_repo_id=row.id).all()
        assert len(chunks) == 10
        for chunk in chunks:
            assert chunk.content == f"body of {chunk.path}"

    def test_a_rate_limit_inside_the_pool_is_still_a_rate_limit(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 4)
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(8)]
        client = _FailingClient(_tree([(p, 5) for p in paths]),
                                {f"blob-{p}": b"x" for p in paths}, fail_on="blob-f5.py")

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_RATE_LIMITED
        assert "rate limit" in out.detail


class TestIncrementalAndResume:

    def _repo(self, db, paths):
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        return row, tree, blobs

    def test_chunks_are_written_as_batches_finish(self, db, fake_embeddings, monkeypatch):
        """The run dies on the third file. The first two are already stored, and the row
        says which commit they belong to."""
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 1)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py"])
        client = _FailingClient(tree, blobs, fail_on="blob-c.py")

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_RATE_LIMITED
        assert out.ingest_sha == HEAD_SHA
        assert out.commit_sha is None
        assert sorted(c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)) == ["a.py", "b.py"]
        assert out.file_count == 2 and out.chunk_count == 2

    def test_a_retry_resumes_instead_of_starting_over(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 1)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py"])
        failed = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(_FailingClient(tree, blobs, fail_on="blob-c.py")))
        assert failed.status == INDEX_RATE_LIMITED

        retry = FakeClient(tree, blobs)
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(retry))

        assert out.status == INDEX_READY
        assert retry.blob_calls == ["blob-c.py"], "the resumed run re-read files it already had"
        assert out.file_count == 3 and out.chunk_count == 3
        assert out.ingest_sha is None and out.commit_sha == HEAD_SHA

    def test_a_resumed_run_does_not_duplicate_what_it_kept(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 1)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py"])
        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(_FailingClient(tree, blobs, fail_on="blob-c.py")))
        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        paths = [c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)]
        assert sorted(paths) == ["a.py", "b.py", "c.py"]
        assert len(paths) == len(set(paths))

    def test_a_moved_head_starts_clean_rather_than_resuming(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "INDEX_FETCH_CONCURRENCY", 1)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py"])
        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(_FailingClient(tree, blobs, fail_on="blob-c.py")))

        moved = "b" * 40
        retry = _FailingClient(tree, blobs, fail_on=None, head=moved)
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(retry))

        assert out.status == INDEX_READY and out.commit_sha == moved
        assert sorted(retry.blob_calls) == ["blob-a.py", "blob-b.py", "blob-c.py"]
        assert out.chunk_count == 3
        assert db.query(RepoChunk).filter_by(indexed_repo_id=row.id).count() == 3

    def test_re_indexing_a_finished_repo_replaces_rather_than_appends(self, db, fake_embeddings):
        row, tree, blobs = self._repo(db, ["a.py", "b.py"])
        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        smaller_tree = _tree([("a.py", 5)])
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(smaller_tree, blobs)))

        assert out.status == INDEX_READY
        assert [c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)] == ["a.py"]
        assert out.chunk_count == 1 and out.file_count == 1

    def test_spend_is_billed_per_batch_so_a_failed_run_still_shows(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py"])

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(_FailingClient(tree, blobs, fail_on="blob-c.py")))

        usage = db.query(LlmUsage).all()
        assert len(usage) == 2, "each committed batch bills what it spent"
        assert sum(u.tokens for u in usage) == 14

    def test_caps_and_notes_survive_the_batched_path(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "INDEX_MAX_FILES", 2)
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([("a.py", 5), ("b.py", 5), ("c.py", 5)], truncated=True)
        blobs = {"blob-a.py": b"x", "blob-b.py": b"y", "blob-c.py": b"\xff\xfe binary"}
        client = FakeClient(tree, blobs)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "incomplete file list" in out.detail
        assert "1 file(s) were left out" in out.detail

    def test_a_file_that_is_not_utf8_is_counted_across_batches(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([("a.py", 5), ("b.py", 5)])
        client = FakeClient(tree, {"blob-a.py": b"\xff\xfe", "blob-b.py": b"\xff\xfe"})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert "2 file(s) were skipped because they are not UTF-8 text" in out.detail
        assert out.file_count == 0 and out.chunk_count == 0


class TestBudgetDuringIngest:
    """Batches bill as they go, so a large repository can cross the daily cap in the
    middle of its own run. One check before the first file would leave exactly those
    repositories uncapped."""

    def _repo(self, db, paths):
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        return row, tree, blobs

    # The fake embedder bills 7 tokens a chunk and each of these files is one chunk of
    # nine characters, which the estimator prices at 12. A cap of 30 therefore lets three
    # batches through on real spend of 21 and refuses the fourth on an estimate of 33.
    CAP = 30
    BILLED_PER_FILE = 7

    def test_the_cap_stops_a_run_part_way_through(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])
        client = FakeClient(tree, blobs)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_PAUSED
        # Refused before spending, so the wording is about what is left rather than about
        # an allowance already gone. On the platform key, no figures either way.
        assert "This is larger than the AI allowance you have left today" in out.detail
        assert "allowance resets at" in out.detail
        assert "tokens" not in out.detail, "a token count reached somebody on the platform key"
        assert "3 file(s) are already indexed and have been kept" in out.detail
        assert client.blob_calls == ["blob-a.py", "blob-b.py", "blob-c.py", "blob-d.py"]

    def test_the_ledger_never_goes_over_the_cap(self, db, fake_embeddings, monkeypatch):
        """The point of counting before spending. The batch that would have crossed the
        line is refused, so the recorded spend stops under the cap instead of over it."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        billed = sum(u.tokens for u in db.query(LlmUsage).filter_by(user_id=OWNER))
        assert out.status == INDEX_PAUSED
        assert billed == 3 * self.BILLED_PER_FILE
        assert billed <= self.CAP, f"the ledger went over the cap: {billed} > {self.CAP}"

    def test_the_last_batch_is_refused_before_it_is_billed(self, db, fake_embeddings, monkeypatch):
        """The blob for the refused batch is fetched and chunked, and then the embedding
        request is never made. GitHub work is cheap; provider tokens are what is capped."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert fake_embeddings["calls"] == 3, "an embedding request was made past the cap"
        assert db.query(LlmUsage).filter_by(user_id=OWNER).count() == 3

    def test_what_was_paid_for_is_kept_and_still_resumable(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_PAUSED
        assert out.ingest_sha == HEAD_SHA, "without this the retry starts from zero"
        assert out.commit_sha is None
        assert out.file_count == 3 and out.chunk_count == 3
        assert sorted(c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)) == ["a.py", "b.py", "c.py"]

    def test_the_run_resumes_from_paused_after_the_allowance_returns(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])
        paused = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))
        assert paused.status == INDEX_PAUSED

        # A new day: the ledger is counted per UTC day, so the cap is what moves here.
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        retry = FakeClient(tree, blobs)
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(retry))

        assert out.status == INDEX_READY
        assert retry.blob_calls == ["blob-d.py", "blob-e.py"], "it paid twice for files it already had"
        assert out.file_count == 5 and out.chunk_count == 5
        assert out.ingest_sha is None and out.commit_sha == HEAD_SHA
        paths = [c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)]
        assert sorted(paths) == ["a.py", "b.py", "c.py", "d.py", "e.py"]
        assert len(paths) == len(set(paths))

    def test_a_paused_index_is_never_searched(self, db, fake_embeddings, monkeypatch):
        """Paused says the work is intact, not that it is usable. Retrieval reads
        INDEX_READY and nothing else."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.CAP)
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py", "e.py"])
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))
        assert out.status == INDEX_PAUSED
        assert db.query(RepoChunk).filter_by(indexed_repo_id=row.id).count() == 3

        from crescent_core import TokenClaims
        from app.services import chat as chat_service

        caller = TokenClaims(user_id=OWNER, email="dev@example.com", memberships=(),
                             is_platform_admin=False, token_version=0, raw={})
        assert chat_service._searchable_indexes(db, caller, None) == []

    def test_being_over_the_cap_before_any_work_keeps_the_plain_message(self, db, fake_embeddings, monkeypatch):
        """Nothing was indexed, so there is nothing to say about what was kept."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100)
        db.add(LlmUsage(kind=LLM_KIND_EMBEDDING, user_id=OWNER, tokens=500))
        db.commit()
        row, tree, blobs = self._repo(db, ["a.py", "b.py"])
        client = FakeClient(tree, blobs)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert "used today's AI allowance" in out.detail
        assert "already indexed" not in out.detail
        assert client.blob_calls == []
        assert fake_embeddings["calls"] == 0

    def test_a_key_that_bypasses_the_cap_indexes_the_whole_repository(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 10)
        key = "sk-mine-0001"
        db.add(ApiCredential(scope=SCOPE_USER, owner_user_id=OWNER, provider=PROVIDER_OPENAI,
                             key_encrypted=crypto.encrypt(key), last_four=key[-4:],
                             bypass_token_cap=True, created_by_user_id=OWNER))
        db.commit()
        row, tree, blobs = self._repo(db, ["a.py", "b.py", "c.py", "d.py"])

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_READY
        assert out.file_count == 4


class TestSpendThatOutranTheEstimate:
    """The estimate is deliberately generous, but it is still an estimate. The check on
    what has already been billed is what catches a provider that charged more than the
    estimate allowed for, and it runs before any blob is fetched."""

    def test_a_batch_that_billed_more_than_estimated_stops_the_next_one(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100)
        # Bills 100 tokens for a nine-character file the estimator priced at 12.
        monkeypatch.setattr(embeddings, "embed_texts", lambda texts, credential=None: ([[1.0, 0.0, 0.0]] * len(texts), 100 * len(texts)))
        _seed_account(db)
        row = _seed_row(db)
        paths = ["a.py", "b.py", "c.py"]
        client = FakeClient(_tree([(p, 5) for p in paths]), {f"blob-{p}": f"body {p}".encode() for p in paths})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_PAUSED
        assert out.file_count == 1
        assert client.blob_calls == ["blob-a.py"], "the next batch was fetched before the check"
        assert sum(u.tokens for u in db.query(LlmUsage).filter_by(user_id=OWNER)) == 100


class TestProviderRateLimitPausesRatherThanFails:
    """The reported failure: several repositories indexed, one came back as "the
    embedding service is unavailable" because OpenAI asked for a 2.768 second pause on
    tokens per minute. Nothing was wrong and nothing needed to be thrown away."""

    def _repo(self, db, paths=("a.py", "b.py", "c.py")):
        _seed_account(db)
        row = _seed_row(db)
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        return row, FakeClient(tree, blobs)

    def test_a_short_limit_is_waited_out_and_the_index_finishes(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        monkeypatch.setattr("app.services.provider_limits.time.sleep", lambda s: None)
        calls = {"n": 0}

        class Limited(Exception):
            def __init__(self):
                super().__init__("Rate limit reached for text-embedding-3-small on tokens per min (TPM): Limit 1000000, Used 1000000, Requested 46142. Please try again in 2.768s.")
                self.status_code = 429

        class Client:
            class embeddings:
                @staticmethod
                def create(model, input):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise Limited()
                    return type("R", (), {
                        "data": [type("D", (), {"index": i, "embedding": [0.1, 0.2, 0.3]})() for i in range(len(input))],
                        "usage": type("U", (), {"total_tokens": 5})(),
                    })()

        monkeypatch.setattr(embeddings, "_build_client", lambda credential=None: Client())
        row, client = self._repo(db)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_READY
        assert out.file_count == 3
        assert calls["n"] == 2, "the retry never happened"

    def test_a_long_limit_pauses_with_the_work_kept(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 5)
        real = embeddings.embed_texts
        calls = {"n": 0}

        def limited(texts, credential=None):
            calls["n"] += 1
            if calls["n"] > 2:
                raise ProviderRateLimited(1800.0, "embeddings (text-embedding-3-small)")
            return real(texts, credential)

        monkeypatch.setattr(embeddings, "embed_texts", limited)
        row, client = self._repo(db)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_PAUSED, "a transient limit was recorded as a failure"
        assert "busy" in out.detail
        assert "2 file(s) are already indexed and have been kept" in out.detail
        assert "unavailable" not in out.detail
        assert out.ingest_sha == HEAD_SHA
        assert db.query(RepoChunk).filter_by(indexed_repo_id=row.id).count() == 2

    def test_the_paused_run_resumes_where_it_stopped(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 1)
        real = embeddings.embed_texts
        calls = {"n": 0}

        def limited(texts, credential=None):
            calls["n"] += 1
            if calls["n"] > 2:
                raise ProviderRateLimited(1800.0, "embeddings")
            return real(texts, credential)

        monkeypatch.setattr(embeddings, "embed_texts", limited)
        row, client = self._repo(db)
        assert repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client)).status == INDEX_PAUSED

        monkeypatch.setattr(embeddings, "embed_texts", real)
        retry = FakeClient(_tree([(p, 5) for p in ("a.py", "b.py", "c.py")]),
                           {f"blob-{p}": f"body {p}".encode() for p in ("a.py", "b.py", "c.py")})
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(retry))

        assert out.status == INDEX_READY
        assert retry.blob_calls == ["blob-c.py"]
        assert out.file_count == 3 and out.chunk_count == 3

    def test_a_genuine_outage_is_still_reported_as_one(self, db, monkeypatch):
        """Paused means come back. An embedding service that is actually broken has to
        keep saying so, or the difference stops meaning anything."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")

        def broken(texts, credential=None):
            raise embeddings.EmbeddingError("provider is down")

        monkeypatch.setattr(embeddings, "embed_texts", broken)
        row, client = self._repo(db)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_ERROR
        assert "unavailable right now" in out.detail


class TestAnAllowanceTooSmallToEverWork:
    def test_it_says_the_reset_will_not_help(self, db, fake_embeddings, monkeypatch):
        """A batch costing more than a whole day's allowance lands in the same place
        tomorrow. Telling someone to come back after the reset would be advice that can
        never work."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 50)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 5)
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(4)]
        client = FakeClient(_tree([(p, 5) for p in paths]), {f"blob-{p}": b"some content here" for p in paths})

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert out.status == INDEX_PAUSED
        assert "more than a full day's allowance" in out.detail
        assert "Raise the allowance" in out.detail
        assert "after the reset to carry on" not in out.detail


class TestABatchTooBigForTheAllowanceIsSplit:
    """The liveness bug this fixes: a batch priced above the whole allowance was refused
    on every retry, so a repository could never be indexed at any allowance below that
    figure. Refusing the whole batch is not a trade, it is stuck.

    With the fake embedder each of these files is one chunk, estimated at 13 tokens and
    billed at 7.
    """

    ESTIMATE_PER_FILE = 13

    def _repo(self, db, count=8):
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(count)]
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        return row, tree, blobs

    def test_the_estimate_this_class_relies_on(self, db):
        assert llm_budget.estimate_tokens(["body f0.py"]) == self.ESTIMATE_PER_FILE

    def test_a_batch_priced_above_the_whole_allowance_still_makes_progress(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        # One batch of eight is estimated at 104, well above this.
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 40)
        row, tree, blobs = self._repo(db)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_PAUSED
        assert out.file_count > 0, "it refused the whole batch instead of splitting it"
        assert out.file_count == 4 and out.chunk_count == 4
        billed = sum(u.tokens for u in db.query(LlmUsage).filter_by(user_id=OWNER))
        assert billed == 28 and billed <= 40

    def test_splitting_does_not_fetch_a_blob_twice(self, db, fake_embeddings, monkeypatch):
        """The halves carry their blobs with them, so a split costs no GitHub calls."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 40)
        row, tree, blobs = self._repo(db)
        client = FakeClient(tree, blobs)

        repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(client))

        assert len(client.blob_calls) == 8
        assert len(set(client.blob_calls)) == 8

    def test_the_split_run_resumes_and_finishes(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 40)
        row, tree, blobs = self._repo(db)
        paused = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))
        assert paused.status == INDEX_PAUSED and paused.file_count == 4

        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        retry = FakeClient(tree, blobs)
        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(retry))

        assert out.status == INDEX_READY
        assert out.file_count == 8 and out.chunk_count == 8
        assert sorted(retry.blob_calls) == [f"blob-f{i}.py" for i in range(4, 8)]
        paths = [c.path for c in db.query(RepoChunk).filter_by(indexed_repo_id=row.id)]
        assert len(paths) == len(set(paths)) == 8

    def test_a_single_file_that_cannot_fit_is_where_it_stops(self, db, fake_embeddings, monkeypatch):
        """Nothing smaller exists to try, so this is the one case where raising the
        allowance really is the answer."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.ESTIMATE_PER_FILE - 1)
        row, tree, blobs = self._repo(db, count=4)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_PAUSED
        assert out.file_count == 0
        assert "more than a full day's allowance" in out.detail
        assert fake_embeddings["calls"] == 0

    def test_an_allowance_that_fits_one_file_indexes_one_file(self, db, fake_embeddings, monkeypatch):
        """The smallest allowance that is not stuck. It gets somewhere every day rather
        than nowhere for ever."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", self.ESTIMATE_PER_FILE)
        row, tree, blobs = self._repo(db, count=4)

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_PAUSED
        assert out.file_count == 1 and out.chunk_count == 1
        assert "already indexed and have been kept" in out.detail

    def test_files_are_not_counted_twice_when_their_batch_is_split(self, db, fake_embeddings, monkeypatch):
        """A split batch is chunked again as halves, so the counters have to be written
        where a batch commits and nowhere else."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(4)]
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        blobs["blob-f2.py"] = b"\xff\xfe binary"

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_READY
        assert out.file_count == 3
        assert "1 file(s) were skipped because they are not UTF-8 text" in out.detail

    def test_an_undecodable_file_inside_a_split_batch_is_counted_once(self, db, fake_embeddings, monkeypatch):
        """A cap of 60 forces three splits and still finishes, so the completion notes
        are written and can be checked."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "INDEX_BATCH_FILES", 8)
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 60)
        _seed_account(db)
        row = _seed_row(db)
        paths = [f"f{i}.py" for i in range(8)]
        tree = _tree([(p, 5) for p in paths])
        blobs = {f"blob-{p}": f"body {p}".encode() for p in paths}
        blobs["blob-f1.py"] = b"\xff\xfe binary"

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id, make_client=_maker(FakeClient(tree, blobs)))

        assert out.status == INDEX_READY
        assert out.file_count == 7
        assert "1 file(s) were skipped because they are not UTF-8 text" in (out.detail or "")
        assert "2 file(s)" not in (out.detail or "")


class TestTheWorkerSeesTheRequestersDepartments:
    """A Celery task holds an indexed_repos id and nothing else, and department
    membership lives in identity. Without the ids on the row, a background ingest could
    not see a department's key or its allowance and used the platform's instead, so
    indexing stopped earlier than chat did for the same person."""

    DEPT = 7
    MEMBER = dict(user_id=OWNER, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])

    def _dept_key(self, db, key="sk-dept-0001"):
        db.add(ApiCredential(scope=SCOPE_DEPARTMENT, owner_user_id=None, dept_id=self.DEPT,
                             provider=PROVIDER_OPENAI, key_encrypted=crypto.encrypt(key),
                             last_four=key[-4:], bypass_token_cap=False, created_by_user_id=OWNER))
        db.commit()

    def _dept_budget(self, db, cap):
        db.add(TokenBudget(scope=SCOPE_DEPARTMENT, owner_user_id=None, dept_id=self.DEPT,
                           daily_token_cap=cap, created_by_user_id=OWNER))
        db.commit()

    def test_queueing_records_them_on_the_row(self, client, act_as, db, queued):
        act_as(**self.MEMBER)

        body = client.post("/chat/repos", json={"full_name": "org/alpha"}).json()

        assert db.get(IndexedRepo, body["id"]).owner_dept_ids == str(self.DEPT)

    def test_requeueing_rewrites_them(self, client, act_as, db, queued):
        """Someone who moves department gets the departments they are in now."""
        act_as(**self.MEMBER)
        body = client.post("/chat/repos", json={"full_name": "org/alpha"}).json()
        act_as(user_id=OWNER, memberships=[{"dept_id": 9, "team_id": None, "role": "engineer"}])

        client.post("/chat/repos", json={"full_name": "org/alpha"})

        db.expire_all()
        assert db.get(IndexedRepo, body["id"]).owner_dept_ids == "9"

    def test_the_worker_spends_the_departments_key(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        self._dept_key(db)
        _seed_account(db)
        row = _seed_row(db)
        row.owner_dept_ids = str(self.DEPT)
        db.commit()

        repo_index.ingest_repo(db, indexed_repo_id=row.id,
                               make_client=_maker(FakeClient(_tree([("a.py", 5)]), {"blob-a.py": b"x"})))

        assert fake_embeddings["credential"].source == "department"
        assert fake_embeddings["credential"].key == "sk-dept-0001"

    def test_without_them_the_worker_falls_back_to_the_platform_key(self, db, fake_embeddings, monkeypatch):
        """The behaviour before this change, kept for a row queued before the column
        existed."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        self._dept_key(db)
        _seed_account(db)
        row = _seed_row(db)
        row.owner_dept_ids = None
        db.commit()

        repo_index.ingest_repo(db, indexed_repo_id=row.id,
                               make_client=_maker(FakeClient(_tree([("a.py", 5)]), {"blob-a.py": b"x"})))

        assert fake_embeddings["credential"].source == "platform"

    def test_a_raised_department_allowance_reaches_the_worker(self, db, fake_embeddings, monkeypatch):
        """The bug in one assertion: the platform cap would have refused this run before
        it read a single file."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1)
        self._dept_key(db)
        self._dept_budget(db, 0)
        _seed_account(db)
        row = _seed_row(db)
        row.owner_dept_ids = str(self.DEPT)
        db.commit()

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id,
                                     make_client=_maker(FakeClient(_tree([("a.py", 5)]), {"blob-a.py": b"x"})))

        assert out.status == INDEX_READY and out.file_count == 1

    def test_the_same_run_without_the_ids_is_refused_by_the_platform_cap(self, db, fake_embeddings, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1)
        self._dept_key(db)
        self._dept_budget(db, 0)
        _seed_account(db)
        row = _seed_row(db)
        row.owner_dept_ids = None
        db.commit()

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id,
                                     make_client=_maker(FakeClient(_tree([("a.py", 5)]), {"blob-a.py": b"x"})))

        assert out.status == INDEX_PAUSED

    def test_a_lowered_department_allowance_also_reaches_the_worker(self, db, fake_embeddings, monkeypatch):
        """It works in the tightening direction too, which is the half that protects
        somebody rather than enabling them."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-platform-0000")
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        self._dept_budget(db, 1)
        _seed_account(db)
        row = _seed_row(db)
        row.owner_dept_ids = str(self.DEPT)
        db.commit()

        out = repo_index.ingest_repo(db, indexed_repo_id=row.id,
                                     make_client=_maker(FakeClient(_tree([("a.py", 5)]), {"blob-a.py": b"x"})))

        assert out.status == INDEX_PAUSED

    @pytest.mark.parametrize("raw,expected", [
        ("7", (7,)), ("7,9", (7, 9)), ("", ()), (None, ()),
        ("7, 9 ", (7, 9)), ("7,,9", (7, 9)), ("nonsense", ()), ("7,x,9", (7, 9)),
    ])
    def test_parsing_is_forgiving_in_the_narrowing_direction(self, raw, expected):
        assert repo_index.parse_dept_ids(raw) == expected

    def test_formatting_round_trips(self):
        assert repo_index.format_dept_ids([]) is None
        assert repo_index.format_dept_ids([7]) == "7"
        assert repo_index.parse_dept_ids(repo_index.format_dept_ids((7, 9, 11))) == (7, 9, 11)

    def test_an_absurd_number_of_departments_is_truncated_not_refused(self):
        formatted = repo_index.format_dept_ids(list(range(1, 500)))
        assert len(formatted) <= 400
        assert not formatted.endswith(",")
        assert repo_index.parse_dept_ids(formatted)[0] == 1


class TestThePausedMessageSaysWhatToDo:
    """Three different situations, three different pieces of advice. Telling somebody to
    come back after the reset when the reset cannot help is advice that wastes their day."""

    def _stop(self, db, *, used, cap, about_to_spend, files):
        row = _seed_row(db)
        row.file_count = files
        db.commit()
        exc = BudgetExceededError(used, cap, datetime(2026, 8, 26, tzinfo=timezone.utc), about_to_spend=about_to_spend)
        return repo_index._budget_stop(db, row.id, exc).detail

    def test_work_already_done_is_named_and_the_reset_is_the_answer(self, db):
        detail = self._stop(db, used=90, cap=100, about_to_spend=50, files=12)
        assert "12 file(s) are already indexed and have been kept" in detail
        assert "after the reset to carry on from there" in detail

    def test_nothing_done_yet_still_points_at_the_reset(self, db):
        detail = self._stop(db, used=100, cap=100, about_to_spend=0, files=0)
        assert "already indexed" not in detail
        assert "Index this repository again after the reset to carry on." in detail

    def test_a_call_bigger_than_the_whole_allowance_says_the_reset_will_not_help(self, db):
        detail = self._stop(db, used=0, cap=100, about_to_spend=500, files=0)
        assert "more than a full day's allowance" in detail
        assert "Raise the allowance, or ask an admin to." in detail
        assert "after the reset" not in detail

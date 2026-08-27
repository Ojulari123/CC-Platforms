"""Turns a GitHub repository into searchable chunks: walk the tree, keep the text files,
split them into overlapping line windows, embed them, store them.

Two doors lead in — a person's own repositories through their stored OAuth token, and any
public repo by owner/name — and everything past the token decision is one pipeline.

Two things here are load-bearing and easy to get wrong later. The line numbers on a chunk
are quoted back to the person reading an answer, so they are real, 1-indexed and
inclusive. And `detail` on the row is written for that person to read: a cap that bit, a
truncated tree, a missing GitHub connection. It never carries exception text — this
service's failures are logged, not served.
"""
import logging
import math
import re
import struct
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app import celery_app, crypto
from app.config import settings
from app.models import (
    INDEX_ERROR, INDEX_PAUSED, INDEX_PENDING, INDEX_RATE_LIMITED, INDEX_READY, INDEX_RUNNING,
    LLM_KIND_EMBEDDING, PROVIDER_OPENAI, IndexedRepo, LlmUsage, RepoChunk, Repository,
)
from app.services import credentials, embeddings, github_oauth, llm_budget, repositories
from app.services.github_client import GitHubClient, GitHubRateLimited
from app.services.provider_limits import ProviderRateLimited

logger = logging.getLogger(__name__)

# GitHub's own shape: an owner is alphanumeric-or-hyphen and can't lead with a hyphen; a
# repo name also allows dot and underscore. Anything else is refused before it can reach
# a URL — this string is interpolated into /repos/{full_name}/... and a segment like ".."
# or an encoded slash would aim that path somewhere else entirely.
FULL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}$")

# Written into `detail` verbatim so the frontend can recognise this one case and offer a
# reconnect button rather than a dead end. Change the wording and change it there too.
RECONNECT_DETAIL = (
    "Your GitHub connection can't read private repositories. Reconnect your GitHub "
    "account in Pulse and approve the repository access GitHub asks for. Approving "
    "replaces your current connection in place, and the connection you have now keeps "
    "working until you do."
)
NO_ACCOUNT_DETAIL = "Connect your GitHub account in Pulse before indexing a private repository."

# Directories whose contents are installed or generated, never authored. Indexing them
# costs the most tokens and returns the least useful answers.
_SKIP_SEGMENTS = frozenset({
    "node_modules", ".git", "dist", "build", "vendor", "__pycache__",
    ".venv", "venv", "target", ".next", ".nuxt", "coverage",
})
_SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".tif", ".tiff", ".psd",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".flac", ".ogg", ".m4a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dylib", ".dll", ".exe", ".wasm",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3", ".bin", ".dat", ".pack", ".idx",
})
_SKIP_SUFFIXES = (".lock", ".min.js", ".min.css", ".map")

# Rough enough: the model's own tokeniser would need the model's vocabulary, and this
# number only sizes a chunk in the payload, it is never billed against.
_CHARS_PER_TOKEN = 4

class IndexRefused(Exception):
    """A reason the caller can act on — no connected account, missing scope, a name that
    isn't a repository. The message goes straight into `detail`, so it is written for a
    person and never carries anything internal."""

def is_valid_full_name(full_name: str) -> bool:
    if not FULL_NAME_RE.match(full_name or ""):
        return False
    # "." and ".." match the character class above and are exactly the segments that
    # would climb out of the path once this is interpolated into a GitHub URL.
    return all(part not in (".", "..") for part in full_name.split("/"))

def is_indexable_path(path: str) -> bool:
    lowered = (path or "").lower()
    if not lowered:
        return False
    if any(segment in _SKIP_SEGMENTS for segment in lowered.split("/")):
        return False
    if lowered.endswith(_SKIP_SUFFIXES):
        return False
    name = lowered.rsplit("/", 1)[-1]
    # rfind, and > 0 not >= 0: a leading dot is a dotfile (.gitignore), not an extension.
    dot = name.rfind(".")
    return dot <= 0 or name[dot:] not in _SKIP_EXTENSIONS

def chunk_lines(text: str, *, size: int, overlap: int) -> list[tuple[int, int, str]]:
    """Line windows of `size`, overlapping by `overlap`, each with the real 1-indexed
    inclusive line range it came from.

    The overlap is the whole point: a function that straddles a window boundary is cut in
    half in both neighbours, and neither half retrieves well. With an overlap it appears
    whole in at least one window.
    """
    lines = text.splitlines()
    if not lines:
        return []
    step = max(1, size - max(0, overlap))
    windows: list[tuple[int, int, str]] = []
    for start in range(0, len(lines), step):
        window = lines[start:start + size]
        windows.append((start + 1, start + len(window), "\n".join(window)))
        if start + size >= len(lines):
            break
    return windows

def token_estimate(content: str) -> int:
    return max(1, len(content) // _CHARS_PER_TOKEN)

def _is_sqlite(db: Session) -> bool:
    return db.bind.dialect.name == "sqlite"

def _encode_vector(db: Session, vector: list[float]):
    """Postgres takes the list of floats straight into a vector column. SQLite has no
    vector type, so the same numbers go in as little-endian float32 bytes."""
    return struct.pack(f"<{len(vector)}f", *vector) if _is_sqlite(db) else list(vector)

def _decode_vector(raw) -> list[float]:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = bytes(raw)
        return list(struct.unpack(f"<{len(data) // 4}f", data))
    return list(raw)

def _cosine_distance(a: list[float], b: list[float]) -> float:
    # strict=False: a stored vector of the wrong width is a data problem to read as a
    # poor match, not one to raise out of a search.
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)

def _close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()

def _token_for(db: Session, row: IndexedRepo) -> str | None:
    account = github_oauth.get_account(db, row.owner_user_id)
    if row.is_public:
        # A public repo reads fine unauthenticated, but the anonymous quota is 60 calls an
        # hour against 5000 authenticated, and one ingest is hundreds of blobs. The
        # owner's token is used purely for the higher ceiling.
        return crypto.decrypt(account.access_token_encrypted) if account else None
    if account is None:
        raise IndexRefused(NO_ACCOUNT_DETAIL)
    if not github_oauth.has_repo_scope(account):
        raise IndexRefused(RECONNECT_DETAIL)
    return crypto.decrypt(account.access_token_encrypted)

def _select_blobs(nodes: list[dict]) -> tuple[list[dict], int, int]:
    """Filtered file list, how many were dropped for size, and how many the file cap left
    behind. The two counts are returned rather than logged because a partial index has to
    say so on the row."""
    picked: list[dict] = []
    oversize = 0
    for node in nodes:
        if node.get("type") != "blob":
            continue
        path = node.get("path") or ""
        if not is_indexable_path(path):
            continue
        if (node.get("size") or 0) > settings.INDEX_MAX_FILE_BYTES:
            oversize += 1
            continue
        picked.append(node)
    dropped = max(0, len(picked) - settings.INDEX_MAX_FILES)
    return picked[:settings.INDEX_MAX_FILES], oversize, dropped

def format_dept_ids(dept_ids: "tuple[int, ...] | list[int]") -> str | None:
    """Departments as a comma separated string, or None for nobody. Truncated to what the
    column holds rather than raised on: a person in forty departments is not a reason to
    refuse to index their repository."""
    joined = ",".join(str(int(d)) for d in dept_ids)
    return joined[:400].rsplit(",", 1)[0] if len(joined) > 400 else (joined or None)

def parse_dept_ids(raw: str | None) -> tuple[int, ...]:
    """Anything unparseable reads as no departments, which is the old behaviour and the
    safe direction: it can only narrow what the worker may reach."""
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return tuple(out)

def _batched(nodes: list[dict], size: int) -> list[list[dict]]:
    size = max(1, size)
    return [nodes[start:start + size] for start in range(0, len(nodes), size)]

def _fetch_blobs(client, full_name: str, nodes: list[dict], workers: int) -> list[bytes]:
    """Blob bytes for each node, in the order the nodes were given.

    One request per file, done one at a time, is what made a three thousand file
    repository an hour of waiting on the network with a worker doing nothing. The pool is
    bounded rather than unbounded because GitHub's quota and this process's memory are
    both finite, and because a burst wide enough to trip the secondary rate limit costs
    more time than it saves.

    Order is restored by index rather than taken from completion order: a vector filed
    against the wrong path would cite the wrong file, silently.

    An exception from any blob is re-raised here, GitHubRateLimited included. Queued work
    is cancelled on the way out so a rate limit does not leave the pool retrying against
    the same wall for every file still in the batch.
    """
    if workers <= 1 or len(nodes) <= 1:
        return [client.get_blob(full_name, node["sha"]) for node in nodes]

    blobs: list[bytes] = [b""] * len(nodes)
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(client.get_blob, full_name, node["sha"]): i for i, node in enumerate(nodes)}
        for future in as_completed(futures):
            blobs[futures[future]] = future.result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return blobs

def _chunk_batch(nodes: list[dict], blobs: list[bytes]) -> tuple[list[dict], int, int]:
    """Chunks for one batch of files, how many files produced any, and how many were not
    text. Nothing outside this batch is held, which is what keeps memory flat as a
    repository grows."""
    pending: list[dict] = []
    files_read = 0
    undecodable = 0
    for node, raw in zip(nodes, blobs, strict=True):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            undecodable += 1
            continue
        windows = chunk_lines(text, size=settings.INDEX_CHUNK_LINES, overlap=settings.INDEX_CHUNK_OVERLAP)
        if not windows:
            continue
        files_read += 1
        for start_line, end_line, content in windows:
            pending.append({"path": node["path"], "start_line": start_line, "end_line": end_line, "content": content})
    return pending, files_read, undecodable

def _stored_paths(db: Session, indexed_repo_id: int) -> set[str]:
    return set(db.scalars(select(RepoChunk.path).where(RepoChunk.indexed_repo_id == indexed_repo_id).distinct()))

def _prepare_run(db: Session, row: IndexedRepo, commit_sha: str | None) -> set[str]:
    """Decide between resuming and starting clean, and return the paths already stored.

    A run resumes only when `ingest_sha` matches the commit about to be indexed, so the
    stored chunks are known to come from the same snapshot of the same repository. Any
    other case — a first run, a finished run being re-indexed, a repository whose HEAD has
    moved since the failure — clears the chunks and starts over, which is what keeps a
    re-index a replacement rather than two snapshots answering at once.

    The clearing now happens before the writes instead of in the same transaction as
    them, so a failed first run leaves a partial index behind where it used to leave the
    previous one intact. Nothing serves it: search only reads indexes in the ready state,
    and a failed run is not ready.
    """
    resuming = bool(commit_sha) and row.ingest_sha == commit_sha
    if resuming:
        done = _stored_paths(db, row.id)
        logger.info("ingest_repo resuming %s at %s: %d file(s) already stored", row.full_name, commit_sha, len(done))
    else:
        db.execute(delete(RepoChunk).where(RepoChunk.indexed_repo_id == row.id))
        done = set()
        row.file_count = 0
        row.chunk_count = 0
    row.ingest_sha = commit_sha
    db.commit()
    return done

def _files_already_indexed(db: Session, indexed_repo_id: int) -> int:
    """How many files this row has committed. Read back rather than passed in: a counter
    in the loop may not exist yet when a failure lands early, and after the rollback the
    row is the only place the number is still true."""
    db.rollback()
    row = db.get(IndexedRepo, indexed_repo_id)
    return int(row.file_count or 0) if row is not None else 0

def _budget_stop(db: Session, indexed_repo_id: int, exc: Exception) -> IndexedRepo:
    """The daily allowance ran out part way through an ingest.

    Everything already committed stays, and `ingest_sha` stays with it, so indexing this
    repository again after the reset carries on from where it stopped rather than paying
    a second time for files that are already embedded.

    The row lands in INDEX_PAUSED rather than INDEX_ERROR. Retrieval treats the two the
    same, because only INDEX_READY is ever searched and a partial index must not answer
    questions. The difference is for whoever is reading the row: paused says the work is
    intact and the run will pick it up, where error says something went wrong.
    """
    files_kept = _files_already_indexed(db, indexed_repo_id)
    detail = str(exc)
    if getattr(exc, "cap", 0) and exc.about_to_spend > exc.cap:
        # One batch costs more than a whole day's allowance, so waiting for the reset
        # would land in exactly the same place tomorrow. Saying "try again later" here
        # would be advice that can never work.
        detail += (
            " A batch of this repository's files needs more than a full day's allowance, "
            "so waiting for the reset will not get past this. Raise the allowance, or ask "
            "an admin to."
        )
    elif files_kept:
        detail += (
            f" {files_kept:,} file(s) are already indexed and have been kept. "
            "Index this repository again after the reset to carry on from there."
        )
    else:
        detail += " Index this repository again after the reset to carry on."
    return _finish(db, indexed_repo_id, INDEX_PAUSED, detail)

def _finish(db: Session, indexed_repo_id: int, status: str, detail: str | None) -> IndexedRepo:
    db.rollback()
    row = db.get(IndexedRepo, indexed_repo_id)
    row.status = status
    row.detail = (detail or "")[:2000] or None
    row.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row

def ingest_repo(db: Session, *, indexed_repo_id: int, make_client: Callable[[str | None], object] | None = None) -> IndexedRepo:
    row = db.get(IndexedRepo, indexed_repo_id)
    if row is None:
        raise LookupError(f"indexed repository {indexed_repo_id} does not exist")
    make_client = make_client or (lambda token: GitHubClient(token or ""))

    row.status = INDEX_RUNNING
    row.started_at = datetime.now(timezone.utc)
    row.detail = None
    db.commit()

    full_name = row.full_name
    notes: list[str] = []
    client = None
    stage = "connecting to GitHub"
    try:
        if not is_valid_full_name(full_name):
            raise IndexRefused("That is not a valid repository name. Use owner/name.")
        client = make_client(_token_for(db, row))

        stage = "reading the repository"
        meta = client.get_repo(full_name)
        ref = meta.get("default_branch") or "HEAD"
        head = client.get_commit(full_name, ref)
        commit_sha = head.get("sha")

        stage = "listing the repository's files"
        tree = client.get_tree(full_name, commit_sha or ref)
        if tree.get("truncated"):
            # GitHub caps one recursive tree response. Indexing what came back and saying
            # nothing would leave an assistant confidently unaware of half a monorepo.
            notes.append("GitHub returned an incomplete file list for this repository, so some files are missing from the index.")
        selected, oversize, over_cap = _select_blobs(tree.get("tree") or [])
        if oversize:
            notes.append(f"{oversize} file(s) were skipped for being larger than {settings.INDEX_MAX_FILE_BYTES:,} bytes.")
        if over_cap:
            notes.append(f"{over_cap} file(s) were left out: this index holds at most {settings.INDEX_MAX_FILES:,} files.")

        # This runs in Celery, so there is no request token to resolve a key from. The
        # departments the requester belonged to were written onto the row when they asked,
        # which is what lets a department's key and a department's allowance be reached
        # here at all. Pinned to OpenAI because embeddings are.
        #
        # The two go together deliberately. A department may only raise an allowance above
        # what it inherits when it has a key of its own, so honouring a raised department
        # allowance while spending the platform's key would let a department raise the
        # platform's spending. Whose money and how much of it are one question.
        dept_ids = parse_dept_ids(row.owner_dept_ids)
        credential = credentials.resolve_for_user_id(db, row.owner_user_id, dept_ids=dept_ids, provider=PROVIDER_OPENAI)
        # Checked here, not only when the request came in: /mine can enqueue many repos at
        # once, and a cap the worker doesn't enforce is not a cap. Checked again inside
        # the loop below, because this run spends as it goes.
        llm_budget.check_budget(db, row.owner_user_id, kind=LLM_KIND_EMBEDDING, credential=credential, dept_ids=dept_ids)

        stage = "reading file contents"
        done = _prepare_run(db, row, commit_sha)
        todo = [node for node in selected if node["path"] not in done]
        files_read = len(done)
        chunks_written = row.chunk_count
        undecodable = 0
        tokens = 0

        # One batch at a time: fetch, chunk, embed, write, commit. Everything a batch
        # holds is dropped before the next one starts, so peak memory is set by
        # INDEX_BATCH_FILES and not by the size of the repository. Each commit is also a
        # checkpoint — a failure after this point costs the current batch, not the run.
        #
        # A queue rather than a plain loop, because a batch too expensive for what is left
        # of the allowance is halved and put back rather than refused. Its blobs travel
        # with it, so splitting costs no extra GitHub calls.
        queue = deque((batch, None) for batch in _batched(todo, settings.INDEX_BATCH_FILES))
        while queue:
            batch, blobs = queue.popleft()
            # Every batch, not once at the start. Each batch now bills what it spent, so
            # a repository large enough to matter can cross the cap in the middle of its
            # own run; a single check before the first file would let exactly those
            # repositories spend without limit. Stopping here keeps what is already
            # stored and leaves it resumable.
            try:
                llm_budget.check_budget(db, row.owner_user_id, kind=LLM_KIND_EMBEDDING, credential=credential, dept_ids=dept_ids)
            except llm_budget.BudgetExceededError as exc:
                return _budget_stop(db, indexed_repo_id, exc)

            stage = "reading file contents"
            if blobs is None:
                blobs = _fetch_blobs(client, full_name, batch, settings.INDEX_FETCH_CONCURRENCY)
            pending, batch_files, batch_undecodable = _chunk_batch(batch, blobs)
            if not pending:
                # Counted here rather than above, because a batch that gets split is
                # chunked again as halves and its files would otherwise count twice.
                undecodable += batch_undecodable
                files_read += batch_files
                continue

            stage = "creating embeddings"
            # Checked again with the text in hand. The check above only knows what has
            # already been billed, so on its own it lets this batch cross the cap and
            # records the overspend afterwards. Here the exact input is known, so the
            # batch is refused before the request is made rather than after.
            texts = [chunk["content"] for chunk in pending]
            try:
                llm_budget.check_budget(
                    db, row.owner_user_id, kind=LLM_KIND_EMBEDDING, credential=credential,
                    dept_ids=dept_ids, estimated_tokens=llm_budget.estimate_tokens(texts),
                )
            except llm_budget.BudgetExceededError as exc:
                # Too expensive as a whole does not mean too expensive in parts. Half of
                # it may well fit, and refusing the lot would mean a repository whose
                # batch costs more than the allowance could never be indexed at all: the
                # same batch would be refused on every retry, at every allowance below
                # that figure, for ever. So it is halved and both halves go back to the
                # front of the queue, in order, with their blobs.
                #
                # One file that still does not fit is the end of the line. Nothing smaller
                # exists to try, and that is the case where the answer really is to raise
                # the allowance.
                if len(batch) > 1:
                    half = len(batch) // 2
                    queue.appendleft((batch[half:], blobs[half:]))
                    queue.appendleft((batch[:half], blobs[:half]))
                    logger.info(
                        "ingest_repo splitting a batch of %d for %s: %d estimated tokens is more than the allowance leaves",
                        len(batch), full_name, llm_budget.estimate_tokens(texts),
                    )
                    continue
                return _budget_stop(db, indexed_repo_id, exc)
            undecodable += batch_undecodable
            files_read += batch_files
            vectors, batch_tokens = embeddings.embed_texts(texts, credential)

            stage = "saving the index"
            written = [
                RepoChunk(
                    indexed_repo_id=row.id,
                    path=chunk["path"][:1000],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                    content=chunk["content"],
                    token_estimate=token_estimate(chunk["content"]),
                    embedding=_encode_vector(db, vector),
                )
                # strict=True: a short vector list would silently pair chunks with the wrong
                # embeddings, which is an index that answers plausibly and wrongly.
                for chunk, vector in zip(pending, vectors, strict=True)
            ]
            db.add_all(written)
            chunks_written += len(written)
            tokens += batch_tokens
            # Billed per batch rather than once at the end. A run that dies half way
            # still spent what it spent, and a ledger that only records finished runs
            # would let a repeatedly failing index spend without ever showing up.
            spend = LlmUsage(report_id=None, kind=LLM_KIND_EMBEDDING, user_id=row.owner_user_id, dept_id=credentials.paying_dept_id(credential), tokens=batch_tokens)
            db.add(spend)
            row.file_count = files_read
            row.chunk_count = chunks_written
            db.commit()
            # Dropped from the session once they are safely stored. Without this the
            # identity map keeps a handle on every chunk of every batch, and "held in
            # memory until the end" comes back by a quieter route.
            for saved in (*written, spend):
                db.expunge(saved)

        if undecodable:
            notes.append(f"{undecodable} file(s) were skipped because they are not UTF-8 text.")

        stage = "saving the index"
        row.commit_sha = commit_sha
        # Cleared last: while it is set, the chunks below it are a partial ingest of that
        # commit and a retry may keep them. Null means the row is whole.
        row.ingest_sha = None
        row.file_count = files_read
        row.chunk_count = chunks_written
        row.status = INDEX_READY
        row.detail = " ".join(notes)[:2000] or None
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        logger.info("ingest_repo: %s files=%d chunks=%d tokens=%d", full_name, files_read, chunks_written, tokens)
        return row
    except IndexRefused as exc:
        logger.info("ingest_repo refused %s: %s", full_name, exc)
        return _finish(db, indexed_repo_id, INDEX_ERROR, str(exc))
    except llm_budget.BudgetExceededError as exc:
        return _finish(db, indexed_repo_id, INDEX_ERROR, str(exc))
    except GitHubRateLimited as exc:
        logger.warning("ingest_repo rate-limited on %s: %s", full_name, exc)
        minutes = max(1, round(exc.wait_seconds / 60))
        return _finish(db, indexed_repo_id, INDEX_RATE_LIMITED, f"GitHub's rate limit was reached. Try again in about {minutes} minute(s).")
    except ProviderRateLimited as exc:
        # The provider's own per-minute throughput, not the daily allowance and not an
        # outage. Everything embedded so far is stored and `ingest_sha` still points at
        # the commit, so this is paused rather than failed and the retry carries on.
        minutes = max(1, round(exc.wait_seconds / 60))
        logger.warning("ingest_repo paused on %s: %s", full_name, exc)
        files_kept = _files_already_indexed(db, indexed_repo_id)
        detail = f"The embedding service is busy and asked for about {minutes} minute(s). "
        if files_kept:
            detail += f"{files_kept:,} file(s) are already indexed and have been kept. "
        detail += "Index this repository again shortly to carry on from there."
        return _finish(db, indexed_repo_id, INDEX_PAUSED, detail)
    except embeddings.EmbeddingError:
        # Not interpolated: an EmbeddingError wraps the provider's own exception, which
        # can name request URLs, models and organisation ids. embeddings.py logs it.
        logger.exception("ingest_repo could not embed %s (indexed_repo id=%s)", full_name, indexed_repo_id)
        return _finish(db, indexed_repo_id, INDEX_ERROR, "The embedding service is unavailable right now. Try again shortly.")
    except Exception:
        # Whatever was raised can carry URLs, tokens in query strings and driver
        # internals, and this row is served straight back to the user. The row keeps what
        # they can act on; the exception and its traceback go to the log.
        logger.exception("ingest_repo failed for %s while %s (indexed_repo id=%s)", full_name, stage, indexed_repo_id)
        return _finish(db, indexed_repo_id, INDEX_ERROR, f"Indexing failed while {stage}. The service log has the details for index {indexed_repo_id}.")
    finally:
        _close(client)

def search_chunks(db: Session, *, indexed_repo_id: int, query_vector: list[float], k: int = 8) -> list[RepoChunk]:
    """The retrieval seam, and the one place the two dialects diverge.

    On Postgres the ordering and the limit both go to the database. Measured on pgvector
    0.8 with 3000 chunks, the planner answers this shape with the btree on
    indexed_repo_id plus a top-N sort rather than the HNSW index — the repository filter
    is what rules HNSW out. So this is an exact nearest-neighbour search within one
    repository, which is more accurate than an approximate one and linear in that
    repository's chunk count. The HNSW index is there for when that stops being fast
    enough and the query is reshaped around it; see migration 0008.

    The SQLite branch reads every chunk and ranks in Python. It exists so the tests around
    retrieval can run without a Postgres. It is not a production path.
    """
    base = select(RepoChunk).where(RepoChunk.indexed_repo_id == indexed_repo_id, RepoChunk.embedding.isnot(None))
    if not _is_sqlite(db):
        return list(db.scalars(base.order_by(RepoChunk.embedding.cosine_distance(query_vector)).limit(k)))
    rows = list(db.scalars(base))
    rows.sort(key=lambda row: (_cosine_distance(query_vector, _decode_vector(row.embedding)), row.id))
    return rows[:k]

def _owned(db: Session, user: TokenClaims, indexed_repo_id: int) -> IndexedRepo:
    """404, not 403, on someone else's index — the same convention as
    repositories.get_repository, and for the same reason: a 403 confirms the row exists."""
    row = db.get(IndexedRepo, indexed_repo_id)
    if row is None or row.owner_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Indexed repository not found")
    return row

def list_indexed_repos(db: Session, user: TokenClaims, *, limit: int, offset: int) -> tuple[list[IndexedRepo], int]:
    base = select(IndexedRepo).where(IndexedRepo.owner_user_id == user.user_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(IndexedRepo.full_name, IndexedRepo.id).limit(limit).offset(offset))
    return list(rows), total

def get_indexed_repo(db: Session, user: TokenClaims, indexed_repo_id: int) -> IndexedRepo:
    return _owned(db, user, indexed_repo_id)

def delete_indexed_repo(db: Session, user: TokenClaims, indexed_repo_id: int) -> None:
    row = _owned(db, user, indexed_repo_id)
    db.delete(row)
    db.commit()

class RepoNotVisible(Exception):
    """The requester can no longer see a private repository Pulse tracks. Separate from
    IndexRefused because this one never becomes `detail` on a row: the row would then say
    a private repository by that name exists."""

def _queue(db: Session, user: TokenClaims, full_name: str, *, is_public: bool) -> IndexedRepo:
    """Upsert on (owner, full_name): asking for the same repo twice re-indexes it rather
    than making a second row that would drift out of date beside the first.

    Indexing a private repository Pulse tracks copies its source into Pulse and answers
    chat questions out of that copy, so it is gated on the same rule as reading the repo
    row. Checked again in chat._searchable_indexes, because access can lapse long after
    the index was built."""
    owner_user_id = user.user_id
    known = db.scalar(select(Repository).where(Repository.full_name == full_name))
    if known is not None and known.private and not repositories._can_see_repo(db, user, known):
        raise RepoNotVisible(full_name)
    row = db.scalar(select(IndexedRepo).where(IndexedRepo.owner_user_id == owner_user_id, IndexedRepo.full_name == full_name))
    if row is None:
        row = IndexedRepo(owner_user_id=owner_user_id, full_name=full_name)
        db.add(row)
    dept_ids = user.dept_ids
    # Rewritten on every request, so re-indexing after a move carries the departments the
    # person is in now rather than the ones they were in the first time.
    row.owner_dept_ids = format_dept_ids(dept_ids)
    row.repo_id = known.id if known else None
    row.is_public = is_public
    row.status = INDEX_PENDING
    row.detail = None
    row.started_at = None
    row.finished_at = None
    return row

def queue_indexes(db: Session, rows: list[IndexedRepo]) -> list[IndexedRepo]:
    """The rows are committed before the tasks go out, because the worker reads them back
    by id and would race an uncommitted one. That leaves the opposite hazard: a pending
    row with no task behind it never moves again, so a refused dispatch is written onto
    every row that did not get one."""
    from app.tasks import index_repo  # late: app.tasks imports this module

    for i, row in enumerate(rows):
        try:
            celery_app.dispatch(index_repo, row.id)
        except celery_app.BrokerUnavailableError:
            for stuck in rows[i:]:
                stuck.status = INDEX_ERROR
                stuck.detail = celery_app.BROKER_UNAVAILABLE_DETAIL
            db.commit()
            raise
    return rows

def queue_index(db: Session, row: IndexedRepo) -> IndexedRepo:
    return queue_indexes(db, [row])[0]

def request_public_index(db: Session, user: TokenClaims, full_name: str) -> IndexedRepo:
    if not is_valid_full_name(full_name):
        raise HTTPException(status_code=422, detail="Give the repository as owner/name, for example cyphercrescent/pulse")
    llm_budget.check_budget(db, user.user_id, kind=LLM_KIND_EMBEDDING, credential=credentials.resolve_credential(db, user, provider=PROVIDER_OPENAI), dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin)
    # A repo Pulse already tracks knows whether it is private, and treating a private one
    # as public here would fail later as an unexplained 404 from GitHub instead of the
    # "connect your account" message the private path gives.
    known = db.scalar(select(Repository).where(Repository.full_name == full_name))
    try:
        row = _queue(db, user, full_name, is_public=not (known is not None and known.private))
    except RepoNotVisible:
        # 404, not 403, and the same wording as repositories.get_repository: a 403 here
        # would confirm that a private repository by that name is tracked.
        raise HTTPException(status_code=404, detail="Repository not found")
    db.commit()
    db.refresh(row)
    return row

def request_own_repos(db: Session, user: TokenClaims, make_client: Callable[[str], object] | None = None) -> list[IndexedRepo]:
    account = github_oauth.get_account(db, user.user_id)
    if account is None:
        raise HTTPException(status_code=409, detail="Connect your GitHub account in Pulse first.")
    if not github_oauth.has_repo_scope(account):
        raise HTTPException(status_code=409, detail=RECONNECT_DETAIL)
    llm_budget.check_budget(db, user.user_id, kind=LLM_KIND_EMBEDDING, credential=credentials.resolve_credential(db, user, provider=PROVIDER_OPENAI), dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin)

    make_client = make_client or (lambda token: GitHubClient(token))
    client = make_client(crypto.decrypt(account.access_token_encrypted))
    try:
        found = client.list_repos_for_token()
    finally:
        _close(client)

    rows: list[IndexedRepo] = []
    for data in found:
        full_name = data.get("full_name") or ""
        if not is_valid_full_name(full_name):
            logger.warning("skipping a repository GitHub named %r: not a valid owner/name", full_name)
            continue
        try:
            rows.append(_queue(db, user, full_name, is_public=not data.get("private", False)))
        except RepoNotVisible:
            # Skipped rather than raised: /mine is a batch, and one repository the
            # requester has lost Pulse access to should not refuse the other twenty.
            logger.info("skipping %s for user %s: no longer visible in Pulse", full_name, user.user_id)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows

def github_status(db: Session, user: TokenClaims) -> dict:
    account = github_oauth.get_account(db, user.user_id)
    has_scope = github_oauth.has_repo_scope(account)
    reconnect_required = account is not None and not has_scope
    return {
        "connected": account is not None,
        "has_repo_scope": has_scope,
        "reconnect_required": reconnect_required,
        "detail": RECONNECT_DETAIL if reconnect_required else None,
    }

"""Questions answered out of the indexed repositories, with the excerpts kept.

The order of writes here is the part worth reading twice. The question is committed on
its own, before the model is called, so a provider outage costs the answer and not what
the person typed. The answer, its citations and the token ledger row then land in one
commit, for the reason generation.py spells out: a second commit means a failed ledger
write 500s work that was already saved, so the caller retries and pays for it twice.
"""
import logging
import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.config import settings
from app.models import (
    INDEX_READY, LLM_KIND_CHAT, ROLE_ASSISTANT, ROLE_USER,
    ChatCitation, ChatConversation, ChatMessage, IndexedRepo, LlmUsage,
)
from app.services import ai_provider, chat_prompts, credentials, embeddings, llm_budget, repo_index

logger = logging.getLogger(__name__)

# A question longer than this is a document, not a question, and the schema refuses it
# before the service is reached. Repeated here because the Celery-free path is not the
# only way in: any future caller of answer() gets the same ceiling.
MAX_CONTENT_CHARS = 4000

# Ceiling on how much retrieved code goes into one prompt. CHAT_TOP_K chunks of the
# default window size sit comfortably under it; a repository of very long lines does not,
# and a prompt over the model's context window is rejected outright rather than trimmed
# by the provider. Same cap-and-flag shape as generation._collect_week_activity: what was
# cut is counted and the payload says so, so the model can hedge instead of guessing.
MAX_CONTEXT_CHARS = 40_000

DEFAULT_TITLE = "New conversation"
_TITLE_CHARS = 60

# A file path as it appears in prose, in two shapes. One carries directories, and a slash
# is a strong enough signal that any extension is taken at face value. The other is a bare
# name, where "Task.serializer" and "app.conf" look exactly like a file and an extension —
# a real answer about code is full of dotted attribute references. So a bare name only
# counts when its extension is one this platform actually indexes. The optional trailing
# ":12-40" is matched so a stray line reference is stripped rather than breaking the path
# it is stuck to.
_SOURCE_EXTENSIONS = frozenset({
    "py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "vue", "svelte",
    "go", "rs", "rb", "java", "kt", "kts", "swift", "scala", "php", "cs",
    "c", "h", "cc", "cpp", "hpp", "m", "mm", "sh", "bash", "zsh", "ps1",
    "sql", "css", "scss", "sass", "less", "html", "htm", "xml", "svg",
    "json", "yml", "yaml", "toml", "ini", "cfg", "properties", "gradle",
    "md", "mdx", "rst", "txt", "tf", "proto", "graphql", "prisma",
})
_PATH_IN_PROSE_RE = re.compile(
    r"(?:(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]*[A-Za-z0-9_\-]\.[A-Za-z][A-Za-z0-9]{0,9}"
    r"|[A-Za-z0-9_\-]+\.[A-Za-z][A-Za-z0-9]{1,9})"
    r"(?::\d+(?:-\d+)?)?"
)

# When the answer names no file at all, this many top-ranked excerpts are cited so the
# reader still has somewhere to start. Small on purpose: an unattributed answer has no
# evidence that any particular excerpt is what it was built from.
_UNNAMED_ANSWER_CITATIONS = 3

class NoIndexedReposError(Exception):
    pass

def _conversation(db: Session, user: TokenClaims, conversation_id: int) -> ChatConversation:
    """404, not 403, on someone else's conversation — the same convention as
    repositories.get_repository, and for the same reason: a 403 confirms it exists."""
    convo = db.get(ChatConversation, conversation_id)
    if convo is None or convo.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo

def create_conversation(db: Session, user: TokenClaims, title: str | None = None) -> ChatConversation:
    convo = ChatConversation(user_id=user.user_id, title=(title or "").strip()[:300] or DEFAULT_TITLE)
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo

def list_conversations(db: Session, user: TokenClaims, *, limit: int, offset: int) -> tuple[list[ChatConversation], int]:
    base = select(ChatConversation).where(ChatConversation.user_id == user.user_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc()).limit(limit).offset(offset))
    return list(rows), total

def get_conversation(db: Session, user: TokenClaims, conversation_id: int) -> ChatConversation:
    return _conversation(db, user, conversation_id)

def delete_conversation(db: Session, user: TokenClaims, conversation_id: int) -> None:
    convo = _conversation(db, user, conversation_id)
    db.delete(convo)
    db.commit()

def _searchable_indexes(db: Session, user: TokenClaims, indexed_repo_ids: list[int] | None) -> list[IndexedRepo]:
    """The caller's own ready indexes, narrowed to the ids they asked for if they asked.

    Ids that aren't theirs are dropped rather than refused: the scope list comes from a
    checkbox row that can be stale by the time it is sent, and a 404 there would be an
    error message where a narrower search was meant.
    """
    q = select(IndexedRepo).where(IndexedRepo.owner_user_id == user.user_id, IndexedRepo.status == INDEX_READY)
    if indexed_repo_ids:
        q = q.where(IndexedRepo.id.in_(indexed_repo_ids))
    return list(db.scalars(q.order_by(IndexedRepo.id)))

def _retrieve(db: Session, indexes: list[IndexedRepo], query_vector: list[float]) -> list[tuple[IndexedRepo, object]]:
    """Top CHAT_TOP_K chunks across every index in scope, not per index.

    Each index is searched for its own best k and the winners are then ranked against each
    other in Python. Per-index quotas would give a one-file repo the same share of the
    prompt as the monorepo the answer is actually in.
    """
    k = max(1, settings.CHAT_TOP_K)
    scored: list[tuple[float, int, IndexedRepo, object]] = []
    for index in indexes:
        for chunk in repo_index.search_chunks(db, indexed_repo_id=index.id, query_vector=query_vector, k=k):
            distance = repo_index._cosine_distance(query_vector, repo_index._decode_vector(chunk.embedding))
            scored.append((distance, chunk.id, index, chunk))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [(index, chunk) for _, _, index, chunk in scored[:k]]

def _context_payload(question: str, retrieved: list[tuple[IndexedRepo, object]]) -> tuple[dict, list[dict]]:
    """The JSON the model sees, and the citation rows for the same excerpts.

    They are built together so a citation can never quote something the model was not
    shown: if the character cap trimmed an excerpt, the stored snippet is trimmed too.
    """
    excerpts: list[dict] = []
    used = 0
    truncated = False
    for index, chunk in retrieved:
        remaining = MAX_CONTEXT_CHARS - used
        if remaining <= 0:
            truncated = True
            break
        content = chunk.content
        if len(content) > remaining:
            content = content[:remaining]
            truncated = True
        used += len(content)
        excerpts.append({
            "indexed_repo_id": index.id,
            "full_name": index.full_name,
            "path": chunk.path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "snippet": content,
        })
    payload = {
        "question": question,
        "excerpt_count": len(excerpts),
        "retrieved_count": len(retrieved),
        "truncated": truncated,
        "excerpts": excerpts,
    }
    return payload, excerpts

def _paths_named_in(text: str) -> set[str]:
    """Every file path the answer refers to, lowercased and without a line suffix."""
    found: set[str] = set()
    for match in _PATH_IN_PROSE_RE.findall(text or ""):
        path = match.split(":", 1)[0].strip("./").lower()
        # An empty string falls out here too: its extension is "", which is not a source
        # extension, so it needs no guard of its own.
        if "/" not in path and path.rsplit(".", 1)[-1] not in _SOURCE_EXTENSIONS:
            continue
        found.add(path)
    return found

def _mentions(path: str, named: set[str]) -> bool:
    """Whether the answer named this file. A model shortens a long path to its tail or to
    the file name, so both count. Loosening the match only widens which RETRIEVED excerpts
    may be cited; it can never admit one that was not retrieved."""
    lowered = (path or "").lower()
    base = lowered.rsplit("/", 1)[-1]
    return any(lowered.endswith(name) or name.endswith(base) for name in named)

def _select_citations(answer_text: str, excerpts: list[dict], retrieved: list[tuple[IndexedRepo, object]]) -> list[dict]:
    """The citations returned with an answer: what it leaned on, each one checked.

    Two guarantees. A citation's repository, path and line range must equal a chunk that
    was really retrieved and really put in front of the model, so a citation can never
    point somewhere the model was not looking. And a file the answer names that was never
    retrieved produces no citation at all — the model invented that source, and inventing
    a source is the one failure this feature cannot survive.

    Citations are also narrowed to the files the answer names. Returning every retrieved
    excerpt made a short answer arrive with twelve sources, which is more than anyone
    checks, and an unchecked citation is indistinguishable from a wrong one.
    """
    allowed = {(index.full_name, chunk.path, chunk.start_line, chunk.end_line) for index, chunk in retrieved}
    cap = max(1, settings.CHAT_MAX_CITATIONS)

    validated: list[dict] = []
    for excerpt in excerpts:
        key = (excerpt["full_name"], excerpt["path"], excerpt["start_line"], excerpt["end_line"])
        if key not in allowed:
            logger.warning("chat citation dropped: %s %s:%s-%s does not match a retrieved chunk", *key)
            continue
        validated.append(excerpt)

    named = _paths_named_in(answer_text)
    invented = sorted(name for name in named if not any(_mentions(e["path"], {name}) for e in validated))
    if invented:
        logger.warning("chat answer named %d file(s) that were not retrieved: %s", len(invented), ", ".join(invented[:10]))

    # An answer that names no file gives nothing to attribute it to, so the best-ranked
    # few stand in. An answer that names ONLY files that were never retrieved gets none:
    # substituting unrelated excerpts there would dress up the exact failure being caught.
    if not named:
        return validated[:min(_UNNAMED_ANSWER_CITATIONS, cap)]
    return [excerpt for excerpt in validated if _mentions(excerpt["path"], named)][:cap]

def _derive_title(content: str) -> str:
    title = " ".join(content.split())
    if len(title) > _TITLE_CHARS:
        title = title[:_TITLE_CHARS].rstrip() + "…"
    return title or DEFAULT_TITLE

def _embed_question(content: str, credential=None) -> tuple[list[float], int]:
    try:
        vectors, tokens = embeddings.embed_texts([content], credential)
    except embeddings.EmbeddingError as exc:
        # Re-wrapped so the route has one failure to map. The provider's own text stays
        # in the log; embeddings.py has already written it there.
        logger.warning("chat could not embed a question: %s", exc)
        raise ai_provider.AIError("The question could not be embedded") from exc
    return vectors[0], tokens

def answer(db: Session, user: TokenClaims, *, conversation_id: int, content: str, indexed_repo_ids: list[int] | None = None) -> ChatMessage:
    convo = _conversation(db, user, conversation_id)
    content = content.strip()[:MAX_CONTENT_CHARS]
    credential = credentials.resolve_credential(db, user)
    # First of two checks. This one covers the question's own embedding, which is spent
    # before a single word of the answer exists; the second, below, covers the answer.
    llm_budget.check_budget(
        db, user.user_id, kind=LLM_KIND_CHAT, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin,
        estimated_tokens=llm_budget.estimate_tokens(content),
    )

    indexes = _searchable_indexes(db, user, indexed_repo_ids)
    if not indexes:
        raise NoIndexedReposError(
            "None of your repositories have finished indexing, so there is nothing to "
            "answer from yet. Index a repository first, or widen the repositories this "
            "question searches."
        )

    # Committed before the model is called: a provider outage should cost the answer,
    # not the question the person typed.
    question = ChatMessage(conversation_id=convo.id, role=ROLE_USER, content=content)
    db.add(question)
    if convo.title == DEFAULT_TITLE:
        convo.title = _derive_title(content)
    db.commit()

    query_vector, embed_tokens = _embed_question(content, credential)
    retrieved = _retrieve(db, indexes, query_vector)
    payload, excerpts = _context_payload(content, retrieved)

    system_prompt = chat_prompts.build_system_prompt()
    user_prompt = chat_prompts.build_user_prompt(payload)
    # The prompt is only knowable here, after retrieval has decided how much code goes
    # into it, and it is by far the larger half of what a question costs. Checked with
    # that text in hand plus the ceiling on the reply, so the cap refuses the call rather
    # than recording that it happened.
    llm_budget.check_budget(
        db, user.user_id, kind=LLM_KIND_CHAT, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin,
        estimated_tokens=llm_budget.estimate_tokens([system_prompt, user_prompt]) + settings.AI_MAX_OUTPUT_TOKENS,
    )
    result = ai_provider.generate(
        system_prompt,
        user_prompt,
        max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        credential=credential,
    )
    citations = _select_citations(result.text, excerpts, retrieved)
    logger.info(
        "chat answer: user=%s conversation=%s indexes=%s excerpts=%s citations=%s key=%s model=%s tokens=%s truncated=%s",
        user.user_id, convo.id, len(indexes), len(excerpts), len(citations),
        credential.source if credential else "none", result.model, result.token_count, payload["truncated"],
    )

    message = ChatMessage(
        conversation_id=convo.id,
        role=ROLE_ASSISTANT,
        content=result.text,
        model=result.model,
        tokens=result.token_count,
    )
    db.add(message)
    db.flush()
    for excerpt in citations:
        db.add(ChatCitation(message_id=message.id, **excerpt))
    # The embedding of the question is part of what this answer cost, so it is billed on
    # the same row rather than going unmetered.
    db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=user.user_id, tokens=(result.token_count or 0) + embed_tokens))
    convo.updated_at = func.now()
    db.commit()
    db.refresh(message)
    return message

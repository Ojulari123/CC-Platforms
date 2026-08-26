"""Embeddings run on OpenAI and spend LLM_API_KEY, the same key report generation uses.
That is not an oversight: Anthropic has no embeddings API, so the chat assistant's
generation half (Anthropic, see anthropic_llm.py) and its retrieval half (here) sit on
different providers on purpose.

Same two rules as llm.py: the client is built INSIDE the function, never at import, so a
missing key can't break startup or the CI import check; and a provider or timeout error
never bubbles up raw, it becomes EmbeddingError.
"""
import logging
import time
from typing import TYPE_CHECKING
from app.config import settings
from app.services.provider_limits import ProviderRateLimited, call_with_retry

if TYPE_CHECKING:
    from app.services.credentials import ResolvedCredential

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 1.0

class EmbeddingError(Exception):
    pass

def _openai_key(credential: "ResolvedCredential | None") -> str:
    """A caller-supplied key is only usable here when it is an OpenAI one — Anthropic
    has no embeddings API, so an Anthropic credential falls through to the env key
    rather than failing the index."""
    from app.services.credentials import PROVIDER_OPENAI

    if credential is not None and credential.provider == PROVIDER_OPENAI:
        return credential.key
    return settings.LLM_API_KEY

def _build_client(credential: "ResolvedCredential | None" = None):
    key = _openai_key(credential)
    if not key:
        # The variable name is for whoever runs the service, not whoever called it.
        logger.error("Embeddings are not configured: LLM_API_KEY (or OPENAI_API_KEY) is empty; repository indexing is disabled")
        raise EmbeddingError("The repository index is not set up on this server. Contact an admin.")
    from openai import OpenAI

    return OpenAI(api_key=key, timeout=settings.LLM_TIMEOUT_SECONDS)

def _batches(texts: list[str], size: int) -> list[list[str]]:
    return [texts[start:start + size] for start in range(0, len(texts), size)]

def _embed_batch(client, batch: list[str]):
    """Rate limits are waited out; everything else gets one retry and then gives up.

    The two are separated because they mean opposite things. A 429 on tokens per minute
    says the request was fine and the minute was full, so waiting the few seconds the
    provider names is the whole fix. A timeout or a malformed response says something is
    wrong, and hammering it does not help.
    """
    def once():
        return client.embeddings.create(model=settings.EMBEDDING_MODEL, input=batch)

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            return call_with_retry(once, label=f"embeddings ({settings.EMBEDDING_MODEL})")
        except ProviderRateLimited:
            # Not wrapped in EmbeddingError: the caller has to be able to tell a full
            # minute from a broken service, because one is worth resuming and the other
            # is not.
            raise
        except Exception as exc:
            last_err = exc
            logger.warning("embeddings attempt %d failed for a batch of %d: %s", attempt, len(batch), exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)
    raise EmbeddingError(f"Embedding request failed after retry: {last_err}") from last_err

def embed_texts(texts: list[str], credential: "ResolvedCredential | None" = None) -> tuple[list[list[float]], int]:
    """Vectors in the order the texts arrived, plus what the whole call cost in tokens.

    Batched because one request per chunk is one round trip per chunk, and a mid-sized
    repo is thousands of them.

    credential is a caller-supplied key (services/credentials.py); None keeps the env
    behaviour. Its `model` is deliberately ignored — that field overrides the chat
    model, and an embedding column has one fixed width (models.EMBEDDING_DIM).
    """
    if not texts:
        return [], 0

    client = _build_client(credential)
    vectors: list[list[float]] = []
    total_tokens = 0
    for batch in _batches(texts, max(1, settings.INDEX_EMBED_BATCH_SIZE)):
        resp = _embed_batch(client, batch)
        # Sorted by the index the API returns rather than trusting response order: if
        # that order ever changed, relying on it would misfile every vector silently,
        # and a chunk answering for the wrong file is worse than an error.
        rows = sorted(resp.data, key=lambda row: row.index)
        if len(rows) != len(batch):
            raise EmbeddingError(f"Embedding response carried {len(rows)} vectors for {len(batch)} inputs")
        vectors.extend(list(row.embedding) for row in rows)
        total_tokens += getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
    return vectors, total_tokens

"""One door to whichever text model this deployment actually has a key for.

anthropic_llm.py and llm.py each speak to one provider and stay that way. This sits
above them: a surface that just wants prose asks here, and gets Anthropic when the
server has an Anthropic key and OpenAI when it only has that one. Without it a
deployment holding a working OpenAI key still answers 502 on every Anthropic surface,
which is exactly the state this service was in.

Same two rules as the modules below it: the client is built INSIDE the function, never
at import, so a missing key can't break startup or the CI import check; and a provider
error never bubbles up raw, it becomes AIError (a 502).
"""
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from app.config import settings
from app.models import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.services import anthropic_llm
from app.services.provider_limits import ProviderRateLimited, call_with_retry

if TYPE_CHECKING:
    from app.services.credentials import ResolvedCredential

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 1.0

# Re-exported from app.models rather than redeclared: the same two strings are stored in
# api_credentials.provider, and two independent copies would drift.
__all__ = ["PROVIDER_ANTHROPIC", "PROVIDER_OPENAI", "AIError", "AIResult", "active_provider", "generate"]

# Names no variable: the caller is a user, and which key is missing is the operator's
# problem. The variable names go to the log instead.
NOT_CONFIGURED_MESSAGE = "The AI assistant is not set up on this server. Contact an admin."

class AIError(Exception):
    pass

@dataclass
class AIResult:
    text: str
    model: str
    token_count: int | None

def active_provider() -> str | None:
    """Which provider a generate() right now would use, or None if none can run.

    A pinned provider is pinned: AI_PROVIDER=anthropic with no Anthropic key reports
    nothing rather than quietly answering on OpenAI, because "pinned" is usually about
    where the money goes or what the answers are allowed to be trained on.
    """
    pinned = (settings.AI_PROVIDER or "auto").strip().lower()
    if pinned == PROVIDER_ANTHROPIC:
        return PROVIDER_ANTHROPIC if settings.ANTHROPIC_API_KEY else None
    if pinned == PROVIDER_OPENAI:
        return PROVIDER_OPENAI if settings.LLM_API_KEY else None
    if settings.ANTHROPIC_API_KEY:
        return PROVIDER_ANTHROPIC
    if settings.LLM_API_KEY:
        return PROVIDER_OPENAI
    return None

def _build_openai_client(credential: "ResolvedCredential | None" = None):
    key = credential.key if credential is not None else settings.LLM_API_KEY
    from openai import OpenAI

    return OpenAI(api_key=key, timeout=settings.LLM_TIMEOUT_SECONDS)

def _call_openai_once(client, system: str, user: str, max_tokens: int, model: str | None = None):
    return client.chat.completions.create(
        model=model or settings.LLM_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )

def _via_openai(system: str, user: str, *, max_tokens: int, credential: "ResolvedCredential | None" = None) -> AIResult:
    client = _build_openai_client(credential)
    model = (credential.model if credential is not None else None) or settings.LLM_MODEL

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = call_with_retry(lambda: _call_openai_once(client, system, user, max_tokens, model), label=f"OpenAI ({model})")
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("the model returned no text")
            return AIResult(
                text=text,
                model=getattr(resp, "model", model),
                token_count=getattr(getattr(resp, "usage", None), "total_tokens", None),
            )
        except ProviderRateLimited:
            # Left as itself so a caller can say "busy, try shortly" rather than
            # "unavailable". Everything else still becomes AIError.
            raise
        except Exception as exc:
            last_err = exc
            logger.warning("OpenAI generate attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)

    raise AIError(f"OpenAI generation failed after retry: {last_err}") from last_err

def _via_anthropic(system: str, user: str, *, max_tokens: int, credential: "ResolvedCredential | None" = None) -> AIResult:
    # Passed only when there is a credential, so the env path calls anthropic_llm with
    # exactly the arguments it always did.
    override = {} if credential is None else {"api_key": credential.key, "model": credential.model}
    try:
        result = anthropic_llm.generate(system, user, max_tokens=max_tokens, **override)
    except ProviderRateLimited:
        raise
    except Exception as exc:
        # Includes AnthropicError, which is already a wrapped provider error. Re-wrapped
        # rather than re-raised so a caller only ever has to catch AIError.
        raise AIError(f"Anthropic generation failed: {exc}") from exc
    return AIResult(text=result.text, model=result.model, token_count=result.token_count)

def generate(system: str, user: str, *, max_tokens: int, credential: "ResolvedCredential | None" = None) -> AIResult:
    """credential is a caller-supplied key (see services/credentials.py). None keeps the
    env-key behaviour every existing caller relies on."""
    provider = credential.provider if credential is not None else active_provider()
    if provider is None:
        logger.error(
            "No AI provider is configured: AI_PROVIDER=%s and neither ANTHROPIC_API_KEY nor "
            "LLM_API_KEY is set; every AI surface is disabled",
            settings.AI_PROVIDER,
        )
        raise AIError(NOT_CONFIGURED_MESSAGE)
    if provider == PROVIDER_ANTHROPIC:
        return _via_anthropic(system, user, max_tokens=max_tokens, credential=credential)
    return _via_openai(system, user, max_tokens=max_tokens, credential=credential)

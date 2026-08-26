"""Same two rules as llm.py: the client is built INSIDE the function, never at import,
so a missing key can't break startup or the CI import check; and a provider/timeout
error never bubbles up raw, it becomes AnthropicError (a 502).

Deliberately separate from llm.py rather than a shared abstraction — reports stay on
OpenAI and this powers the newer surfaces, so the two providers move independently.
"""
import logging
import time
from dataclasses import dataclass
from app.config import settings
from app.services.provider_limits import ProviderRateLimited, call_with_retry

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 1.0


class AnthropicError(Exception):
    pass

@dataclass
class AnthropicResult:
    text: str
    model: str
    token_count: int | None

def _build_client(api_key: str | None = None):
    key = api_key or settings.ANTHROPIC_API_KEY
    if not key:
        # The variable name is for whoever runs the service, not whoever called it.
        logger.error("Anthropic is not configured: ANTHROPIC_API_KEY is empty; AI rollups are disabled")
        raise AnthropicError("The AI assistant is not set up on this server. Contact an admin.")
    import anthropic

    return anthropic.Anthropic(api_key=key, timeout=settings.ANTHROPIC_TIMEOUT_SECONDS)


def _call_once(client, system: str, user: str, max_tokens: int, model: str | None = None):
    return client.messages.create(
        model=model or settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )


def _text_of(resp) -> str:
    # Anthropic returns a list of content blocks; only the text ones carry the answer.
    return "".join(getattr(block, "text", "") for block in resp.content).strip()


def _tokens_of(resp) -> int | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    return (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)


def generate(system: str, user: str, *, max_tokens: int, api_key: str | None = None, model: str | None = None) -> AnthropicResult:
    """api_key and model override the environment for one call — that is how a
    caller-supplied key (services/credentials.py) reaches Anthropic. Both None keeps the
    behaviour every existing caller relies on."""
    client = _build_client(api_key)
    model = model or settings.ANTHROPIC_MODEL

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = call_with_retry(lambda: _call_once(client, system, user, max_tokens, model), label=f"Anthropic ({model})")
            text = _text_of(resp)
            if not text:
                raise ValueError("the model returned no text")
            return AnthropicResult(
                text=text,
                model=getattr(resp, "model", model),
                token_count=_tokens_of(resp),
            )
        except ProviderRateLimited:
            # A full minute, not a broken provider. Raised as itself so the caller can
            # resume rather than treat the work as lost.
            raise
        except Exception as exc:
            last_err = exc
            logger.warning("Anthropic generate attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)

    raise AnthropicError(f"Anthropic generation failed after retry: {last_err}") from last_err

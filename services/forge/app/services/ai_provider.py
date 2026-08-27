"""One door to the text model, for the playground.

Deliberately a small copy of the same shape Pulse uses rather than an import: services
never depend on each other's code. Forge only ever needs the OpenAI path, so this is the
narrow version — Pulse's provider picking, per-department keys and retry policy stay
there.

Two rules carried over and worth keeping: the client is built INSIDE the function so a
missing key cannot break startup or CI's import check, and a provider error never bubbles
up raw, it becomes AIError.
"""
import logging
from dataclasses import dataclass
from app.config import settings

logger = logging.getLogger(__name__)

# Names no variable: which key is missing is the operator's problem, not the learner's.
NOT_CONFIGURED_MESSAGE = "The language model is not set up on this server. Contact an admin."

class AIError(Exception):
    pass

@dataclass
class AIResult:
    text: str
    model: str
    token_count: int | None

def is_configured() -> bool:
    return bool(settings.LLM_API_KEY)

def generate(system: str, user: str, *, max_tokens: int) -> AIResult:
    if not is_configured():
        logger.error("playground called with no LLM_API_KEY set; the surface is disabled")
        raise AIError(NOT_CONFIGURED_MESSAGE)
    from openai import OpenAI

    client = OpenAI(api_key=settings.LLM_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)
    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except Exception as exc:
        # Provider text can carry request ids and account detail, so it goes to the log and
        # the caller gets one sentence. The key is never in either.
        logger.warning("OpenAI call failed: %s", exc.__class__.__name__)
        raise AIError("The language model could not be reached. Try again shortly.")
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise AIError("The language model returned an empty reply. Try rewording the prompt.")
    return AIResult(text=text, model=getattr(response, "model", settings.LLM_MODEL), token_count=getattr(getattr(response, "usage", None), "total_tokens", None))

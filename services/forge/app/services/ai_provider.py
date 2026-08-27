"""One door to the model, for the playground and for questions about an image.

Deliberately a small copy of the same shape Pulse uses rather than an import: services
never depend on each other's code. Forge only ever needs the OpenAI path, so this is the
narrow version — Pulse's provider picking, per-department keys and retry policy stay
there.

Two rules carried over and worth keeping: the client is built INSIDE the function so a
missing key cannot break startup or CI's import check, and a provider error never bubbles
up raw, it becomes AIError.
"""
import base64, logging
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

def _client():
    if not is_configured():
        logger.error("the model was called with no LLM_API_KEY set; the surface is disabled")
        raise AIError(NOT_CONFIGURED_MESSAGE)
    from openai import OpenAI

    return OpenAI(api_key=settings.LLM_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)

def generate(system: str, user: str, *, max_tokens: int) -> AIResult:
    client = _client()
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

def describe_image(system: str, user: str, image_bytes: bytes, *, mime: str, max_tokens: int) -> AIResult:
    """Same door, with an image alongside the text. The image travels as base64 inside the
    message, so nothing has to be hosted anywhere the provider can reach."""
    client = _client()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ]},
            ],
        )
    except Exception as exc:
        logger.warning("OpenAI vision call failed: %s", exc.__class__.__name__)
        raise AIError("The language model could not be reached. Try again shortly.")
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise AIError("The language model returned an empty reply. Try rewording the question.")
    return AIResult(text=text, model=getattr(response, "model", settings.LLM_MODEL), token_count=getattr(getattr(response, "usage", None), "total_tokens", None))

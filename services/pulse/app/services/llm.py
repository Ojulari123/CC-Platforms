"""
I used a wrapper because the rest of Pulse calls `generate_summaries(...)` and gets back a
plain `LLMResult`. Swapping providers, or mocking in tests, means replacing this one
function (no OpenAI types leak into the generation service or routes)

Two rules this module keeps:
- The OpenAI client is built INSIDE the function, never at import. A missing key must
  never break `the CI import check or startup.
- A provider/timeout error never bubbles up raw. We do one retry, then raise a typed
  `LLMError` the route maps to a clean 502.
"""
import json
import logging
import time
from dataclasses import dataclass
from app.config import settings
from app.services import prompts

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 1.0  # short pause before the single retry


class LLMError(Exception):
    """The provider failed (timeout, API error, or a malformed response) after a retry,
    or is misconfigured. Routes turn this into a 502 with a real message."""

@dataclass
class LLMResult:
    summary_manager: str
    summary_exec: str
    next_week_goals: str
    model: str
    token_count: int | None

def _build_client():
    """Construct the OpenAI client lazily. Raises LLMError if no key is configured so a
    misconfigured deploy gives a real message instead of crashing later."""
    if not settings.LLM_API_KEY:
        raise LLMError(
            "LLM is not configured: LLM_API_KEY is empty. Set it in the environment to "
            "enable report generation."
        )
    from openai import OpenAI

    return OpenAI(api_key=settings.LLM_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)


def _call_once(client, activity_payload: dict):
    return client.chat.completions.create(
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": prompts.build_system_prompt()},
            {"role": "user", "content": prompts.build_user_prompt(activity_payload)},
        ],
        response_format={"type": "json_schema", "json_schema": prompts.SUMMARY_SCHEMA},
    )


def generate_summaries(activity_payload: dict) -> LLMResult:
    """Ask the LLM for the three weekly-report summaries.

    Retries once on any provider error with a short backoff, then raises LLMError.
    Never lets a raw provider exception escape.
    """
    client = _build_client()

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = _call_once(client, activity_payload)
            content = resp.choices[0].message.content
            data = json.loads(content)
            token_count = getattr(getattr(resp, "usage", None), "total_tokens", None)
            return LLMResult(
                summary_manager=data["summary_manager"],
                summary_exec=data["summary_exec"],
                next_week_goals=data["next_week_goals"],
                model=getattr(resp, "model", settings.LLM_MODEL),
                token_count=token_count,
            )
        except Exception as exc:  # provider error, timeout, or malformed JSON/fields
            last_err = exc
            logger.warning("LLM generate_summaries attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)

    raise LLMError(f"LLM generation failed after retry: {last_err}") from last_err

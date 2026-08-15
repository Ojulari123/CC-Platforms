"""Two rules this module keeps: the OpenAI client is built INSIDE the function, never
at import, so a missing key can't break startup or the CI import check; and a
provider/timeout error never bubbles up raw, it becomes LLMError (a 502).
"""
import json
import logging
import time
from dataclasses import dataclass
from app.config import settings
from app.services import prompts

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 1.0


class LLMError(Exception):
    pass

@dataclass
class LLMResult:
    summary_manager: str
    summary_exec: str
    next_week_goals: str
    model: str
    token_count: int | None

def _build_client():
    if not settings.LLM_API_KEY:
        # The variable name is for whoever runs the service, not whoever called it.
        logger.error("LLM is not configured: LLM_API_KEY is empty; report generation is disabled")
        raise LLMError("The report generator is not set up on this server. Contact an admin.")
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
        except Exception as exc:
            last_err = exc
            logger.warning("LLM generate_summaries attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)

    raise LLMError(f"LLM generation failed after retry: {last_err}") from last_err

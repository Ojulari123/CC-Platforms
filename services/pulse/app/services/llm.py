"""Two rules this module keeps: the OpenAI client is built INSIDE the function, never
at import, so a missing key can't break startup or the CI import check; and a
provider/timeout error never bubbles up raw, it becomes LLMError (a 502).
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from app.config import settings
from app.services.provider_limits import ProviderRateLimited, call_with_retry
from app.models import PROVIDER_OPENAI
from app.services import prompts

if TYPE_CHECKING:
    from app.services.credentials import ResolvedCredential

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

def _openai_key(credential: "ResolvedCredential | None") -> str:
    """A caller-supplied key is only usable here when it is an OpenAI one — this module
    speaks the OpenAI JSON-schema API and nothing else, so an Anthropic credential falls
    back to the env key rather than failing the report."""
    if credential is not None and credential.provider == PROVIDER_OPENAI:
        return credential.key
    return settings.LLM_API_KEY

def _model_for(credential: "ResolvedCredential | None") -> str:
    if credential is not None and credential.provider == PROVIDER_OPENAI and credential.model:
        return credential.model
    return settings.LLM_MODEL

def _build_client(credential: "ResolvedCredential | None" = None):
    key = _openai_key(credential)
    if not key:
        # The variable name is for whoever runs the service, not whoever called it.
        logger.error("LLM is not configured: LLM_API_KEY is empty; report generation is disabled")
        raise LLMError("The report generator is not set up on this server. Contact an admin.")
    from openai import OpenAI

    return OpenAI(api_key=key, timeout=settings.LLM_TIMEOUT_SECONDS)


def _call_once(client, activity_payload: dict, system_prompt: str, model: str):
    return client.chat.completions.create(
        model=model,
        max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompts.build_user_prompt(activity_payload)},
        ],
        response_format={"type": "json_schema", "json_schema": prompts.SUMMARY_SCHEMA},
    )


def generate_summaries(activity_payload: dict, *, system_prompt: str | None = None, credential: "ResolvedCredential | None" = None) -> LLMResult:
    """system_prompt is the base prompt with a persona already applied; credential is a
    caller-supplied key (services/credentials.py). Both None keeps the env behaviour
    every existing caller relies on."""
    client = _build_client(credential)
    system_prompt = system_prompt or prompts.build_system_prompt()
    model = _model_for(credential)

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = call_with_retry(lambda: _call_once(client, activity_payload, system_prompt, model), label=f"OpenAI ({model})")
            content = resp.choices[0].message.content
            data = json.loads(content)
            token_count = getattr(getattr(resp, "usage", None), "total_tokens", None)
            return LLMResult(
                summary_manager=data["summary_manager"],
                summary_exec=data["summary_exec"],
                next_week_goals=data["next_week_goals"],
                model=getattr(resp, "model", model),
                token_count=token_count,
            )
        except ProviderRateLimited:
            # A full minute, not a broken provider. Raised as itself so the caller can
            # resume rather than treat the work as lost.
            raise
        except Exception as exc:
            last_err = exc
            logger.warning("LLM generate_summaries attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)

    raise LLMError(f"LLM generation failed after retry: {last_err}") from last_err

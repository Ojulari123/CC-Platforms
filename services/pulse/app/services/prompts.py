"""Prompt text and the output contract for weekly report generation.

Kept in its own module so prompts are versionable and reviewable apart from the
LLM plumbing. PROMPT_VERSION bumps whenever the wording or schema below changes,
so we can tell which prompt produced a given draft.
"""
import json

PROMPT_VERSION = "2026-08-05.1"

SYSTEM_PROMPT = (
    "You are an engineering reporting assistant for CypherCrescent's Pulse platform. "
    "You are given one engineer's GitHub activity for a single week in a single repository "
    "(commits, pull requests, reviews, issues) as structured data. Write factual, specific "
    "weekly report text grounded ONLY in the activity provided. Do not invent work that is not "
    "in the data. If the activity is sparse, say so plainly rather than padding. "
    "Return your answer using the required JSON schema with three separate fields."
)

# Per-field guidance, folded into the user message so the model knows what each field is for.
_FIELD_GUIDANCE = (
    "Produce three fields:\n"
    "- summary_manager: manager-facing. Specific and concrete — what was built, changed, "
    "reviewed or fixed, referencing PR/issue numbers where useful. A few sentences.\n"
    "- summary_exec: exec-lite. One or two short sentences on outcomes and momentum, no jargon, "
    "no PR numbers.\n"
    "- next_week_goals: a short, plausible set of next steps implied by the in-progress work "
    "(open PRs/issues). Keep it grounded; if nothing is clearly implied, suggest continuing the "
    "current thread of work."
)

def build_system_prompt() -> str:
    """The system prompt — stable across calls for a given PROMPT_VERSION."""
    return SYSTEM_PROMPT

def build_user_prompt(activity_payload: dict) -> str:
    return (
        f"{_FIELD_GUIDANCE}\n\n"
        "Here is the engineer's activity for the week as JSON:\n"
        f"{json.dumps(activity_payload, default=str)}"
    )

# OpenAI structured-output schema: forces the three fields back as separate strings.
SUMMARY_SCHEMA = {
    "name": "weekly_report_summaries",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary_manager": {"type": "string"},
            "summary_exec": {"type": "string"},
            "next_week_goals": {"type": "string"},
        },
        "required": ["summary_manager", "summary_exec", "next_week_goals"],
    },
}

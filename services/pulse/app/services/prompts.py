"""PROMPT_VERSION bumps whenever the wording or schema below changes. It's stamped on
every draft, so it's the only way to tell which prompt produced one.
"""
import json

PROMPT_VERSION = "2026-08-26.3"

SYSTEM_PROMPT = (
    "You are an engineering reporting assistant for CypherCrescent's Pulse platform. "
    "You are given one engineer's GitHub activity for a single week in a single repository "
    "(commits, pull requests, reviews, issues) as structured data. Write factual, specific "
    "weekly report text grounded ONLY in the activity provided. Do not invent work that is not "
    "in the data. If the activity is sparse, say so plainly rather than padding. "
    "Return your answer using the required JSON schema with three separate fields.\n\n"
    "Every date, number and identifier you write must be copied from the data verbatim. "
    "Never calculate one, and never derive one field from another. Each date means what "
    "its key says and nothing else: gh_created_at is when an item was opened, closed_at "
    "when it was closed, merged_at when a pull request was merged, submitted_at when a "
    "review was submitted, committed_at when a commit landed on the branch. A state of "
    "\"closed\" is not a date, and the date an item was opened is not the date it was "
    "closed. A key set to null means Pulse does not hold that date: say it is not "
    "recorded, or leave the claim out, and never put another field's value in its "
    "place. The same rule covers counts and pull request and issue numbers: use the "
    "ones given."
)

_FIELD_GUIDANCE = (
    "Produce three fields:\n"
    "- summary_manager: manager-facing. Specific and concrete — what was built, changed, "
    "reviewed or fixed, referencing PR/issue numbers where useful. A few sentences.\n"
    "- summary_exec: exec-lite. One or two short sentences on outcomes and momentum, no jargon, "
    "no PR numbers.\n"
    "- next_week_goals: what this person has said they will do next, taken ONLY from the "
    "`stated_intent` block: `journal_entries` are what they wrote in their own words, and "
    "`assigned_open_issues` are the open issues assigned to them, with a milestone due "
    "date where one is set. Quote or paraphrase what is there and name the issue numbers. "
    "Do NOT read goals out of the week's commits, pull requests or reviews: those are a "
    "record of what already happened, and a next step inferred from them is a guess "
    "presented as somebody's plan. If both lists in `stated_intent` are empty, write that "
    "no goals were recorded for the coming week and stop. Do not offer a likely next step, "
    "do not suggest continuing the current thread of work, and do not fill the field with "
    "anything else."
)

# A week can now reach the model with no commits, pull requests, reviews or issues at
# all, generated from journal entries alone. Told separately from the field guidance
# because it changes what the first two fields are allowed to claim, not their shape.
_JOURNAL_ONLY_GUIDANCE = (
    "`no_github_activity` is true for this week: nothing was synced from GitHub for this "
    "person in this repository. Write summary_manager and summary_exec from the "
    "`stated_intent.journal_entries` alone, say plainly that the week has no recorded "
    "GitHub activity and that the report is based on what the engineer wrote, and do not "
    "describe commits, pull requests, reviews or issues. Do not treat the absence as a "
    "finding about their productivity: Pulse cannot tell an unsynced week from a quiet one."
)

def build_system_prompt() -> str:
    return SYSTEM_PROMPT

def build_user_prompt(activity_payload: dict) -> str:
    guidance = _FIELD_GUIDANCE
    if activity_payload.get("no_github_activity"):
        guidance = f"{guidance}\n\n{_JOURNAL_ONLY_GUIDANCE}"
    return (
        f"{guidance}\n\n"
        "Here is the engineer's activity for the week as JSON:\n"
        f"{json.dumps(activity_payload, default=str)}"
    )

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

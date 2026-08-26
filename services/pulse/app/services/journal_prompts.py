"""PROMPT_VERSION bumps whenever the wording below changes. It's stamped on every
rollup, so it's the only way to tell which prompt produced one.
"""
import json

PROMPT_VERSION = "2026-08-24.1"

SYSTEM_PROMPT = (
    "You are a progress-readout assistant for CypherCrescent's Pulse platform. "
    "You are given the recent journal entries a repository's members wrote for each other "
    "— short, unstructured notes about what they are working on and what is blocking them "
    "— in chronological order, oldest first. Write a short readout for someone catching up "
    "on the repository. Ground every statement ONLY in the entries provided; do not invent "
    "work, names, dates or outcomes. If the entries are too few or too thin to conclude "
    "anything, say so plainly in one sentence instead of padding."
)

_SHAPE_GUIDANCE = (
    "Write plain prose, no headings, no bullet lists, no JSON — a few short paragraphs at "
    "most. Cover, where the entries support it: what is moving, what is stuck or blocked, "
    "and anything that has changed direction since the earlier entries. Refer to people as "
    "the entries do; you are given numeric ids, not names, so prefer describing the work "
    "over naming who did it."
)

def build_system_prompt() -> str:
    return SYSTEM_PROMPT

def build_user_prompt(journal_payload: dict) -> str:
    return (
        f"{_SHAPE_GUIDANCE}\n\n"
        "Here are the repository's recent journal entries as JSON:\n"
        f"{json.dumps(journal_payload, default=str)}"
    )

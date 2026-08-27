"""A daily ceiling on playground spend per user, checked before the call rather than
reported after it.

Same idea as Pulse's llm_budget, and the same reason for the estimate sitting above what
the provider bills: an estimate that comes in low turns a cap into a report of
overspending. Simpler than Pulse's because Forge has one surface and one key — no
per-department credentials, no bypass.
"""
import math
import re
from datetime import datetime, time, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import LLM_KIND_PLAYGROUND, LlmUsage

# Character-shaped approximation, no tokeniser dependency. A run of letters or digits is
# about a token per three characters, punctuation is about one each, and anything outside
# ASCII costs at least one. The safety factor is what turns "about" into a bound.
_RUN_RE = re.compile(r"\s+|\w+|[^\w\s]")
_CHARS_PER_WORD_TOKEN = 3.0
_SAFETY = 1.15
_PER_INPUT_TOKENS = 4

class BudgetExceeded(Exception):
    """Message written for the learner."""

def _day_start() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)

def estimate_tokens(text: str) -> int:
    word_chars = punctuation = whitespace_runs = 0
    for run in _RUN_RE.finditer(text or ""):
        piece = run.group(0)
        if piece[0].isspace():
            whitespace_runs += 1
        elif piece[0].isalnum():
            word_chars += len(piece)
        else:
            punctuation += 1
    non_ascii = sum(1 for char in (text or "") if ord(char) > 127)
    raw = word_chars / _CHARS_PER_WORD_TOKEN + punctuation + whitespace_runs * 0.25 + non_ascii
    return math.ceil(raw * _SAFETY) + _PER_INPUT_TOKENS

def tokens_used_today(db: Session, user_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(LlmUsage.tokens), 0)).where(LlmUsage.user_id == user_id, LlmUsage.created_at >= _day_start())) or 0

def check_budget(db: Session, user_id: int, *, about_to_spend: int) -> None:
    cap = settings.LLM_DAILY_TOKEN_CAP
    if cap <= 0:
        return
    used = tokens_used_today(db, user_id)
    # Two conditions catching different things: the allowance is already gone, or this one
    # call would take it past the line.
    if used < cap and used + max(0, about_to_spend) <= cap:
        return
    remaining = max(0, cap - used)
    raise BudgetExceeded(f"This needs about {about_to_spend:,} tokens and you have {remaining:,} of your {cap:,} daily tokens left. The allowance resets at 00:00 UTC.")

def record_usage(db: Session, *, user_id: int, run_id: int | None, tokens: int, kind: str = LLM_KIND_PLAYGROUND) -> None:
    """Rows here are never deleted: the ledger is the only record of what was spent."""
    db.add(LlmUsage(run_id=run_id, user_id=user_id, tokens=max(0, tokens), kind=kind))

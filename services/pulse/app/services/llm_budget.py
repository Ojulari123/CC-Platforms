"""A hard daily ceiling on AI spend per user, not a warning after the fact.

Every surface that costs tokens writes to the same `llm_usage` ledger, so the cap is
counted across all of them together: a per-surface budget would just be three separate
ways to spend the same money.

The check counts what a call is about to cost BEFORE making it. Counting only what has
already been billed lets one call cross the cap and the ledger record it afterwards,
which is a cap that reports overspending rather than one that prevents it. What the cap
is, and who may change it, lives in services/credentials.py beside the keys, because the
two answer halves of one question: whose money, and how much of it.
"""
import logging
import math
import re
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Iterable
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import LlmUsage
from app.services.credentials import SOURCE_PLATFORM, resolve_cap

if TYPE_CHECKING:
    from app.services.credentials import ResolvedCredential

logger = logging.getLogger(__name__)

# No tokeniser is installed and adding a dependency for one is out of scope, so this is a
# measured approximation. It has to sit ABOVE what the provider bills, because an
# estimate that comes in low puts the cap back to reporting overspending instead of
# preventing it.
#
# Counting characters alone is not enough, and the reason is worth keeping. A first
# version divided characters by 2.6 and underestimated 5 of 500 real inputs, worst case
# 0.79x on a pinned requirements file: "amqp==5.3.1" is eleven characters and seven or
# eight tokens, because every piece of punctuation is its own token. Prose and code run
# nearer four characters per token, so no single divisor covers both without pricing
# ordinary code at three times what it costs.
#
# So the shape below follows the tokeniser instead of averaging over it: a run of letters
# and digits costs about a token per three characters, each punctuation mark costs about
# one, runs of whitespace are mostly absorbed into their neighbours, and a character
# outside ASCII costs at least one on its own. The safety factor is what turns "about"
# into a bound.
#
# Measured on 500 chunks drawn one per distinct file from celery/celery, pallets/flask
# and this repository, priced against what OpenAI actually billed. The safety factor was
# then walked down against that same measurement:
#
#   safety  overall  worst   underestimates
#     1.20    1.89x  1.11x   0
#     1.15    1.82x  1.06x   0     <- here
#     1.10    1.74x  1.02x   0
#     1.08    1.71x  1.00x   0
#     1.06    1.68x  0.98x   2
#
# 1.15 is where it stops. Below 1.08 the estimate starts coming in under what was billed,
# and 1.08 to 1.10 buys a few per cent of efficiency for a margin of nought to two per
# cent, which is not a margin at all against content unlike the sample. The small gap
# between 1.20 and 1.15 says the safety factor was never carrying much: the structural
# terms above are what make this accurate.
#
# Overestimating cannot compound. Each check adds an estimate for ONE call to a `used`
# figure that is real billed spend, so the error is bounded by a single call and spent as
# headroom, never as overspend.
_RUN_RE = re.compile(r"[A-Za-z0-9]+|[^A-Za-z0-9\s]|\s+")
_ESTIMATE_CHARS_PER_WORD_TOKEN = 3.0
_ESTIMATE_PUNCTUATION_TOKENS = 1.0
_ESTIMATE_WHITESPACE_TOKENS = 0.15
_ESTIMATE_NON_ASCII_TOKENS = 1.0
_ESTIMATE_SAFETY = 1.15
# For short inputs, where the request's own framing dominates: a 9-character file was
# billed 5 tokens.
_ESTIMATE_PER_INPUT_TOKENS = 8

class BudgetExceededError(Exception):
    """Carries when the allowance comes back, because "try again later" without a time
    is the same as "no".

    The message obeys one rule: meaning for users, mechanism for whoever pays. A token is
    the model vendor's unit of accounting and means nothing to somebody who is just
    trying to get an answer, so the default wording tells them their allowance for today
    is used up and when it comes back. Somebody spending their own key, or a department's,
    gets the figures instead, because those reconcile against a provider invoice and a
    vague sentence would be worse than useless to them.

    Two shapes within each, because two different things are being refused. Spent means
    the allowance is gone. Too large means there is some left but not enough for this
    call, which is the difference between waiting for the reset and retrying something
    smaller. The raw numbers stay on the exception either way, so a caller that has
    somewhere better to put them can.
    """

    def __init__(self, used: int, cap: int, resets_at: datetime, about_to_spend: int = 0, show_figures: bool = False):
        self.used = used
        self.cap = cap
        self.resets_at = resets_at
        self.about_to_spend = about_to_spend
        self.remaining = max(0, cap - used)
        self.show_figures = show_figures
        resets = f"The allowance resets at {resets_at.strftime('%H:%M')} UTC."
        spent = used >= cap
        if show_figures and spent:
            message = f"You have used {used:,} of your {cap:,} daily AI tokens. {resets}"
        elif show_figures:
            message = (
                f"This needs about {about_to_spend:,} tokens and you have {self.remaining:,} "
                f"of your {cap:,} daily AI tokens left. {resets}"
            )
        elif spent:
            message = f"You have used today's AI allowance. {resets}"
        else:
            message = f"This is larger than the AI allowance you have left today. {resets}"
        super().__init__(message)

def _day_start() -> datetime:
    """UTC midnight, not local: the workers, the database and the ledger all run in UTC,
    and a local boundary would move the reset twice a year."""
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)

def tokens_used_today(db: Session, user_id: int) -> int:
    q = select(func.coalesce(func.sum(LlmUsage.tokens), 0)).where(LlmUsage.user_id == user_id, LlmUsage.created_at >= _day_start())
    return db.scalar(q) or 0

def _may_bypass(credential: "ResolvedCredential | None") -> bool:
    """You may only lift a cap on spend you are paying for. The platform's env key is
    never bypassable, whatever the caller asked for — there is no row behind it to carry
    permission, and the cap is the only thing protecting the platform's own account."""
    if credential is None or credential.source == SOURCE_PLATFORM:
        return False
    return bool(credential.bypass_token_cap)

def may_see_figures(credential: "ResolvedCredential | None", *, is_platform_admin: bool = False) -> bool:
    """Whether this person is funding the calls, so token figures are theirs to see.

    A key of their own or their department's is money they can be shown an invoice for;
    the platform's key is not theirs, and a platform admin is told because the platform's
    spend IS theirs. Separate from whether they may raise a cap: a user under a
    department key sees the figures without being able to spend more of that money.
    """
    return is_platform_admin or (credential is not None and credential.source != SOURCE_PLATFORM)

def _estimate_one(text: str) -> int:
    word_chars = punctuation = whitespace_runs = 0
    for run in _RUN_RE.finditer(text):
        piece = run.group(0)
        if piece[0].isspace():
            whitespace_runs += 1
        elif piece[0].isalnum():
            word_chars += len(piece)
        else:
            punctuation += 1
    non_ascii = sum(1 for char in text if ord(char) > 127)
    raw = (
        word_chars / _ESTIMATE_CHARS_PER_WORD_TOKEN
        + punctuation * _ESTIMATE_PUNCTUATION_TOKENS
        + whitespace_runs * _ESTIMATE_WHITESPACE_TOKENS
        + non_ascii * _ESTIMATE_NON_ASCII_TOKENS
    )
    return math.ceil(raw * _ESTIMATE_SAFETY) + _ESTIMATE_PER_INPUT_TOKENS

def estimate_tokens(texts: "str | Iterable[str]") -> int:
    """What these inputs will cost, rounded up and deliberately above the real figure.
    See the constants above for the measurement behind it."""
    if isinstance(texts, str):
        texts = (texts,)
    return sum(_estimate_one(text or "") for text in texts)

def check_budget(db: Session, user_id: int, *, kind: str, credential: "ResolvedCredential | None" = None, dept_ids: "tuple[int, ...] | list[int]" = (), estimated_tokens: int = 0, is_platform_admin: bool = False) -> None:
    """Refuse before spending, not after.

    `estimated_tokens` is what the call about to be made will cost: for an embedding
    request the exact text is already in hand, and for a generation it is the prompt plus
    the max_tokens ceiling on the reply. A caller that passes nothing gets the older
    behaviour, which only refuses someone whose allowance is already gone.

    `is_platform_admin` reaches only the wording of a refusal, never whether one happens.
    A caller holding a token passes it through; a Celery task holding a bare user id
    cannot, and defaults to the wording without figures, which is the safe direction.
    """
    if _may_bypass(credential):
        # Uncapped, not unmetered: the caller's usage still goes into llm_usage, so the
        # spend stays visible.
        return
    cap, _ = resolve_cap(db, user_id, dept_ids=dept_ids)
    show_figures = may_see_figures(credential, is_platform_admin=is_platform_admin)
    if cap <= 0:
        return
    used = tokens_used_today(db, user_id)
    # Two conditions, because they catch different things: the allowance is already gone,
    # or it is not but this call would take it past the line.
    if used < cap and used + max(0, estimated_tokens) <= cap:
        return
    logger.warning(
        "llm budget refused: user=%s kind=%s used=%s about_to_spend=%s cap=%s",
        user_id, kind, used, estimated_tokens, cap,
    )
    raise BudgetExceededError(
        used, cap, _day_start() + timedelta(days=1),
        about_to_spend=max(0, estimated_tokens), show_figures=show_figures,
    )

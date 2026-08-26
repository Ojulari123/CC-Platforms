"""Waiting out a model provider's per-minute limit instead of failing the work.

The failure this exists for: a user indexed several repositories and one came back as
"the embedding service is unavailable", when what OpenAI actually said was

    429 Rate limit reached for text-embedding-3-small on tokens per min (TPM):
    Limit 1000000, Used 1000000, Requested 46142. Please try again in 2.768s.

A three second pause, named to the millisecond, and the run was thrown away because the
retry was one flat second. This is the provider's own throughput limit and has nothing to
do with the daily allowance in llm_budget: nobody is over budget, the minute is just
full.

The shape is copied from github_client._request, which had the same problem first. Read
what the provider says to wait, sleep through short waits, and give up only when the wait
is longer than a worker should be held. What comes back then is ProviderRateLimited,
which callers can tell apart from a real outage, because the right answer to it is to
resume rather than to start again.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from app.config import settings

logger = logging.getLogger(__name__)

# The provider states the wait in prose as well as in a header, and the header is missing
# often enough that the message is worth reading: "Please try again in 2.768s", "try again
# in 1m20s", "Retry after 30 seconds", "try again in 500ms".
#
# Two expressions rather than one. Finding the phrase and reading the duration are
# separate problems, and a single pattern doing both was where "500ms" got read as five
# hundred minutes.
_WAIT_PHRASE_RE = re.compile(r"(?:try again|retry)\s+(?:in|after)\s+", re.IGNORECASE)
_DURATION_PART_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)?",
    re.IGNORECASE,
)
# Longest match wins in the alternation above only because ms precedes m. Kept as a
# multiplier table so adding a unit does not mean touching the parser.
_UNIT_SECONDS = {"": 1.0, "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
                 "ms": 0.001, "millisecond": 0.001, "milliseconds": 0.001,
                 "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0}

class ProviderRateLimited(Exception):
    """The provider is throttling, and it is temporary. Distinct from a provider being
    down, because the work already done is still good and the answer is to come back."""

    def __init__(self, wait_seconds: float, label: str):
        self.wait_seconds = max(0.0, wait_seconds)
        self.resume_at = datetime.now(timezone.utc) + timedelta(seconds=self.wait_seconds)
        super().__init__(
            f"{label} is rate limited; retry in ~{max(1, round(self.wait_seconds / 60))} min "
            f"(resets at {self.resume_at.isoformat(timespec='seconds')})"
        )

def is_rate_limit(exc: Exception) -> bool:
    """A 429, however the provider's SDK chose to express it. Both the OpenAI and the
    Anthropic clients expose `status_code` on the exception or on a `response` hanging off
    it, and both name the class RateLimitError, so this asks three ways rather than
    importing either SDK at module scope."""
    if type(exc).__name__ in ("RateLimitError", "TooManyRequests"):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429

def wait_seconds_for(exc: Exception) -> float | None:
    """How long the provider asked us to wait, or None if it did not say.

    The header wins over the message: it is machine-written and always in seconds, where
    the message is prose that changes between models.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for name in ("retry-after", "Retry-After", "retry-after-ms", "x-ratelimit-reset-tokens"):
        raw = headers.get(name)
        if raw is None:
            continue
        parsed = _parse_duration(str(raw), milliseconds=name.endswith("-ms"))
        if parsed is not None:
            return parsed
    return _wait_from_message(str(exc))

def _parse_duration(raw: str, *, milliseconds: bool = False) -> float | None:
    raw = raw.strip()
    try:
        if milliseconds:
            return float(raw) / 1000.0
        if raw.endswith("ms"):
            return float(raw[:-2]) / 1000.0
        if raw.endswith("s"):
            return float(raw[:-1])
        return float(raw)
    except ValueError:
        return None

def _wait_from_message(message: str) -> float | None:
    """Adds up the parts, so "1m20s" is eighty seconds rather than one or twenty."""
    phrase = _WAIT_PHRASE_RE.search(message)
    if phrase is None:
        return None
    tail = message[phrase.end():]
    total = 0.0
    position = 0
    while True:
        part = _DURATION_PART_RE.match(tail, position)
        if part is None:
            break
        total += float(part.group(1)) * _UNIT_SECONDS.get((part.group(2) or "").lower(), 1.0)
        position = part.end()
        # Only a space may separate two parts of one duration. Anything else means the
        # sentence has moved on and the next number belongs to something else.
        while position < len(tail) and tail[position] == " ":
            position += 1
    return total or None

def _backoff(attempt: int) -> float:
    """What to wait when the provider said nothing. Doubling from two seconds, which is
    the same curve github_client uses."""
    return float(2 ** attempt)

def call_with_retry(fn: Callable[[], object], *, label: str, sleep: Callable[[float], None] = time.sleep) -> object:
    """Run `fn`, waiting out rate limits for as long as PROVIDER_MAX_WAIT_SECONDS allows.

    Only rate limits are retried here. Any other exception is raised immediately, because
    retrying a bad request or a rejected key just makes the same mistake more slowly.
    """
    attempts = max(1, settings.PROVIDER_MAX_RETRIES)
    max_wait = max(0, settings.PROVIDER_MAX_WAIT_SECONDS)
    spent = 0.0
    for attempt in range(1, attempts + 2):
        try:
            return fn()
        except Exception as exc:
            if not is_rate_limit(exc):
                raise
            asked = wait_seconds_for(exc)
            wait = asked if asked is not None else _backoff(attempt)
            # Both conditions matter. One long wait is refused on its own, and a run of
            # short ones is refused once they add up, so a provider throttling every few
            # seconds cannot hold a worker indefinitely by never asking for long.
            if wait > max_wait or spent + wait > max_wait or attempt > attempts:
                logger.warning(
                    "%s rate limited: asked for %ss after %s attempt(s), %ss already waited, giving up",
                    label, round(wait, 2), attempt, round(spent, 2),
                )
                raise ProviderRateLimited(wait, label) from exc
            logger.info(
                "%s rate limited: waiting %ss as the provider asked (attempt %s of %s)",
                label, round(wait, 2), attempt, attempts,
            )
            sleep(wait)
            spent += wait
    raise ProviderRateLimited(0.0, label)

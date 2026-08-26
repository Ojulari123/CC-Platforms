from datetime import datetime, timedelta, timezone
import pytest
from app.config import settings
from app.models import LLM_KIND_EMBEDDING, LLM_KIND_JOURNAL_ROLLUP, LLM_KIND_REPORT, LlmUsage
from app.services import llm_budget
from app.services.llm_budget import BudgetExceededError

USER = 10
OTHER = 11


def _spend(db, user_id, tokens, *, kind=LLM_KIND_REPORT, at=None):
    row = LlmUsage(report_id=None, kind=kind, user_id=user_id, tokens=tokens)
    if at is not None:
        row.created_at = at
    db.add(row)
    db.commit()


def test_nothing_spent_is_zero(db):
    assert llm_budget.tokens_used_today(db, USER) == 0


def test_every_kind_counts_against_the_same_allowance(db):
    _spend(db, USER, 100, kind=LLM_KIND_REPORT)
    _spend(db, USER, 200, kind=LLM_KIND_JOURNAL_ROLLUP)
    _spend(db, USER, 300, kind=LLM_KIND_EMBEDDING)

    assert llm_budget.tokens_used_today(db, USER) == 600


def test_another_user_spend_is_not_counted(db):
    _spend(db, OTHER, 5000)

    assert llm_budget.tokens_used_today(db, USER) == 0


def test_yesterday_does_not_count_against_today(db):
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
    _spend(db, USER, 5000, at=yesterday)
    _spend(db, USER, 7, at=datetime.now(timezone.utc))

    assert llm_budget.tokens_used_today(db, USER) == 7


def test_under_the_cap_passes(db, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
    _spend(db, USER, 999)

    llm_budget.check_budget(db, USER, kind=LLM_KIND_EMBEDDING)


def test_at_the_cap_is_refused_and_says_when_it_resets(db, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
    _spend(db, USER, 1000)

    with pytest.raises(BudgetExceededError) as exc:
        llm_budget.check_budget(db, USER, kind=LLM_KIND_EMBEDDING)

    assert exc.value.used == 1000 and exc.value.cap == 1000
    assert "resets at 00:00 UTC" in str(exc.value)
    assert exc.value.resets_at > datetime.now(timezone.utc)


def test_a_cap_of_zero_means_unlimited(db, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
    _spend(db, USER, 10_000_000)

    llm_budget.check_budget(db, USER, kind=LLM_KIND_EMBEDDING)


def test_a_negative_cap_is_treated_as_unlimited_rather_than_locking_everyone_out(db, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", -5)
    _spend(db, USER, 10)

    llm_budget.check_budget(db, USER, kind=LLM_KIND_EMBEDDING)

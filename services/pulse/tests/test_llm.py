import json
import logging
import pytest
from app.services import llm
from app.services.llm import LLMError, LLMResult

PAYLOAD = {"counts": {"commits": 2, "pull_requests": 1, "reviews": 0, "issues": 0}}

_GOOD_JSON = json.dumps({
    "summary_manager": "Shipped the auth refactor.",
    "summary_exec": "Steady progress.",
    "next_week_goals": "Finish token rotation.",
})

class _FakeMessage:
    def __init__(self, content):
        self.content = content

class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)

class _FakeUsage:
    total_tokens = 321

class _FakeResponse:
    model = "gpt-4o-mini"
    usage = _FakeUsage()

    def __init__(self, content):
        self.choices = [_FakeChoice(content)]

class _FakeCompletions:
    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self._behaviours.pop(0)()

class _FakeClient:
    def __init__(self, behaviours):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(behaviours)})()

def _ok():
    return _FakeResponse(_GOOD_JSON)

def _fail():
    raise RuntimeError("provider timeout")

@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    return slept

def _install_client(monkeypatch, behaviours):
    fake = _FakeClient(behaviours)
    monkeypatch.setattr(llm, "_build_client", lambda credential=None: fake)
    return fake

class TestRetry:
    def test_fails_once_then_succeeds_on_retry(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_fail, _ok])
        result = llm.generate_summaries(PAYLOAD)
        assert isinstance(result, LLMResult)
        assert result.summary_manager == "Shipped the auth refactor."
        assert result.next_week_goals == "Finish token rotation."
        assert result.token_count == 321
        assert fake.chat.completions.calls == 2
        assert no_sleep == [llm._RETRY_BACKOFF_SECONDS]

    def test_fails_on_both_attempts_raises_llmerror(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_fail, _fail])
        with pytest.raises(LLMError):
            llm.generate_summaries(PAYLOAD)
        assert fake.chat.completions.calls == 2
        assert no_sleep == [llm._RETRY_BACKOFF_SECONDS]

class TestMissingKeyIsNotDescribedToTheCaller:
    def test_the_error_does_not_name_the_variable_but_the_log_does(self, monkeypatch, caplog):
        monkeypatch.setattr(llm.settings, "LLM_API_KEY", "")
        with caplog.at_level(logging.ERROR, logger="app.services.llm"):
            with pytest.raises(LLMError) as excinfo:
                llm._build_client()
        assert "LLM_API_KEY" not in str(excinfo.value)
        assert "LLM_API_KEY" in caplog.text

    def test_the_provider_error_stays_out_of_the_llmerror_the_route_sees(self, monkeypatch, no_sleep, caplog):
        """The raw provider exception can carry request URLs and org ids. It belongs in
        the log; routes/reports.py no longer puts LLMError text in a response at all."""
        def _leaky():
            raise RuntimeError("401 from https://api.openai.com/v1/chat/completions org-abc123")

        _install_client(monkeypatch, [_leaky, _leaky])
        with caplog.at_level(logging.WARNING, logger="app.services.llm"):
            with pytest.raises(LLMError):
                llm.generate_summaries(PAYLOAD)
        assert "org-abc123" in caplog.text

import json
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
    monkeypatch.setattr(llm, "_build_client", lambda: fake)
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

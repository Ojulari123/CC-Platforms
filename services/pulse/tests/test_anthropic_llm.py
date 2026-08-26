import logging
import pytest
from app.services import anthropic_llm
from app.services.anthropic_llm import AnthropicError, AnthropicResult

SYSTEM = "You summarise journals."
USER = "entries: []"

class _FakeBlock:
    def __init__(self, text):
        self.text = text

class _FakeUsage:
    input_tokens = 300
    output_tokens = 112

class _FakeResponse:
    model = "claude-sonnet-5"
    usage = _FakeUsage()

    def __init__(self, text):
        self.content = [_FakeBlock(text)]

class _FakeMessages:
    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return self._behaviours.pop(0)()

class _FakeClient:
    def __init__(self, behaviours):
        self.messages = _FakeMessages(behaviours)

def _ok():
    return _FakeResponse("Auth work is moving; the migration is blocked.")

def _fail():
    raise RuntimeError("provider timeout")

def _empty():
    return _FakeResponse("   ")

@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(anthropic_llm.time, "sleep", lambda s: slept.append(s))
    return slept

def _install_client(monkeypatch, behaviours):
    fake = _FakeClient(behaviours)
    monkeypatch.setattr(anthropic_llm, "_build_client", lambda api_key=None: fake)
    return fake

class TestGenerate:
    def test_returns_the_text_model_and_summed_tokens(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_ok])
        result = anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        assert isinstance(result, AnthropicResult)
        assert result.text == "Auth work is moving; the migration is blocked."
        assert result.model == "claude-sonnet-5"
        assert result.token_count == 412
        assert fake.messages.calls == 1
        assert no_sleep == []

    def test_the_system_prompt_and_cap_reach_the_provider(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_ok])
        anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        kwargs = fake.messages.last_kwargs
        assert kwargs["system"] == SYSTEM
        assert kwargs["max_tokens"] == 500
        assert kwargs["messages"] == [{"role": "user", "content": USER}]

    def test_usage_missing_leaves_the_token_count_unknown(self, monkeypatch, no_sleep):
        response = _FakeResponse("text")
        response.usage = None
        _install_client(monkeypatch, [lambda: response])
        assert anthropic_llm.generate(SYSTEM, USER, max_tokens=500).token_count is None

class TestRetry:
    def test_fails_once_then_succeeds_on_retry(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_fail, _ok])
        result = anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        assert result.token_count == 412
        assert fake.messages.calls == 2
        assert no_sleep == [anthropic_llm._RETRY_BACKOFF_SECONDS]

    def test_fails_on_both_attempts_raises_anthropicerror(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_fail, _fail])
        with pytest.raises(AnthropicError):
            anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        assert fake.messages.calls == 2
        assert no_sleep == [anthropic_llm._RETRY_BACKOFF_SECONDS]

    def test_an_empty_answer_is_retried_then_becomes_an_error(self, monkeypatch, no_sleep):
        fake = _install_client(monkeypatch, [_empty, _empty])
        with pytest.raises(AnthropicError):
            anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        assert fake.messages.calls == 2

class TestMissingKeyIsNotDescribedToTheCaller:
    def test_the_error_does_not_name_the_variable_but_the_log_does(self, monkeypatch, caplog):
        monkeypatch.setattr(anthropic_llm.settings, "ANTHROPIC_API_KEY", "")
        with caplog.at_level(logging.ERROR, logger="app.services.anthropic_llm"):
            with pytest.raises(AnthropicError) as excinfo:
                anthropic_llm._build_client()
        assert "ANTHROPIC_API_KEY" not in str(excinfo.value)
        assert "ANTHROPIC_API_KEY" in caplog.text

    def test_a_key_present_builds_a_real_client_without_calling_out(self, monkeypatch):
        monkeypatch.setattr(anthropic_llm.settings, "ANTHROPIC_API_KEY", "sk-test-not-real")
        client = anthropic_llm._build_client()
        assert hasattr(client, "messages")

    def test_the_provider_error_stays_out_of_the_error_the_route_sees(self, monkeypatch, no_sleep, caplog):
        """The raw provider exception can carry request URLs and org ids. It belongs in
        the log; routes/journals.py never puts AnthropicError text in a response."""
        def _leaky():
            raise RuntimeError("401 from https://api.anthropic.com/v1/messages org-abc123")

        _install_client(monkeypatch, [_leaky, _leaky])
        with caplog.at_level(logging.WARNING, logger="app.services.anthropic_llm"):
            with pytest.raises(AnthropicError):
                anthropic_llm.generate(SYSTEM, USER, max_tokens=500)
        assert "org-abc123" in caplog.text

import logging
import pytest
from app.config import Settings
from app.services import ai_provider, anthropic_llm
from app.services.ai_provider import AIError, AIResult
from app.services.anthropic_llm import AnthropicError, AnthropicResult

SYSTEM = "You answer from code."
USER = "what does main.py do?"

class _FakeUsage:
    total_tokens = 275

class _FakeMessage:
    def __init__(self, content):
        self.content = content

class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)

class _FakeResponse:
    model = "gpt-4o-mini-2024-07-18"

    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()

class _FakeCompletions:
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
        self.chat = type("_Chat", (), {"completions": _FakeCompletions(behaviours)})()

def _ok():
    return _FakeResponse("app/main.py wires the routers together.")

def _fail():
    raise RuntimeError("provider timeout")

def _empty():
    return _FakeResponse("   ")

@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(ai_provider.time, "sleep", lambda s: slept.append(s))
    return slept

@pytest.fixture
def openai_only(monkeypatch):
    monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "sk-openai-not-real")

@pytest.fixture
def anthropic_only(monkeypatch):
    monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "sk-anthropic-not-real")
    monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "")

def _install_openai(monkeypatch, behaviours):
    fake = _FakeClient(behaviours)
    monkeypatch.setattr(ai_provider, "_build_openai_client", lambda credential=None: fake)
    return fake


class TestSelection:
    def test_anthropic_wins_when_both_keys_are_set(self, monkeypatch):
        monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "sk-anthropic-not-real")
        monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "sk-openai-not-real")
        assert ai_provider.active_provider() == "anthropic"

    def test_openai_is_used_when_it_is_the_only_key(self, openai_only):
        assert ai_provider.active_provider() == "openai"

    def test_no_key_at_all_reports_nothing(self, monkeypatch):
        monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "")
        assert ai_provider.active_provider() is None

    def test_pinning_openai_ignores_an_anthropic_key(self, monkeypatch):
        monkeypatch.setattr(ai_provider.settings, "AI_PROVIDER", "openai")
        monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "sk-anthropic-not-real")
        monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "sk-openai-not-real")
        assert ai_provider.active_provider() == "openai"

    def test_a_pinned_provider_with_no_key_does_not_fall_back(self, monkeypatch):
        """Pinning is usually about which bill the tokens land on, so silently spending
        the other provider's key would be the wrong kind of helpful."""
        monkeypatch.setattr(ai_provider.settings, "AI_PROVIDER", "anthropic")
        monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "sk-openai-not-real")
        assert ai_provider.active_provider() is None

    def test_an_unknown_provider_is_refused_by_config(self, monkeypatch):
        with pytest.raises(ValueError):
            monkeypatch.setattr(ai_provider.settings, "AI_PROVIDER", "llama")


class TestOpenAIPath:
    def test_returns_the_text_model_and_tokens(self, monkeypatch, openai_only, no_sleep):
        fake = _install_openai(monkeypatch, [_ok])
        result = ai_provider.generate(SYSTEM, USER, max_tokens=500)
        assert isinstance(result, AIResult)
        assert result.text == "app/main.py wires the routers together."
        assert result.model == "gpt-4o-mini-2024-07-18"
        assert result.token_count == 275
        assert fake.chat.completions.calls == 1
        assert no_sleep == []

    def test_the_system_prompt_and_cap_reach_the_provider(self, monkeypatch, openai_only, no_sleep):
        fake = _install_openai(monkeypatch, [_ok])
        ai_provider.generate(SYSTEM, USER, max_tokens=500)
        kwargs = fake.chat.completions.last_kwargs
        assert kwargs["max_tokens"] == 500
        assert kwargs["messages"] == [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ]

    def test_fails_once_then_succeeds_on_retry(self, monkeypatch, openai_only, no_sleep):
        fake = _install_openai(monkeypatch, [_fail, _ok])
        assert ai_provider.generate(SYSTEM, USER, max_tokens=500).token_count == 275
        assert fake.chat.completions.calls == 2
        assert no_sleep == [ai_provider._RETRY_BACKOFF_SECONDS]

    def test_failing_twice_raises_aierror(self, monkeypatch, openai_only, no_sleep):
        _install_openai(monkeypatch, [_fail, _fail])
        with pytest.raises(AIError):
            ai_provider.generate(SYSTEM, USER, max_tokens=500)

    def test_an_empty_answer_is_retried_then_becomes_an_error(self, monkeypatch, openai_only, no_sleep):
        fake = _install_openai(monkeypatch, [_empty, _empty])
        with pytest.raises(AIError):
            ai_provider.generate(SYSTEM, USER, max_tokens=500)
        assert fake.chat.completions.calls == 2

    def test_a_missing_usage_block_leaves_the_token_count_unknown(self, monkeypatch, openai_only, no_sleep):
        response = _FakeResponse("text")
        response.usage = None
        _install_openai(monkeypatch, [lambda: response])
        assert ai_provider.generate(SYSTEM, USER, max_tokens=500).token_count is None

    def test_a_key_present_builds_a_real_client_without_calling_out(self, openai_only):
        client = ai_provider._build_openai_client()
        assert hasattr(client, "chat")

    def test_the_provider_error_stays_in_the_log(self, monkeypatch, openai_only, no_sleep, caplog):
        def _leaky():
            raise RuntimeError("401 from https://api.openai.com/v1/chat org-abc123")

        _install_openai(monkeypatch, [_leaky, _leaky])
        with caplog.at_level(logging.WARNING, logger="app.services.ai_provider"):
            with pytest.raises(AIError):
                ai_provider.generate(SYSTEM, USER, max_tokens=500)
        assert "org-abc123" in caplog.text


class TestAnthropicPath:
    def test_it_delegates_and_maps_the_result(self, monkeypatch, anthropic_only):
        seen = {}

        def _fake(system, user, *, max_tokens):
            seen.update(system=system, user=user, max_tokens=max_tokens)
            return AnthropicResult(text="from claude", model="claude-sonnet-5", token_count=412)

        monkeypatch.setattr(anthropic_llm, "generate", _fake)
        result = ai_provider.generate(SYSTEM, USER, max_tokens=900)
        assert result == AIResult(text="from claude", model="claude-sonnet-5", token_count=412)
        assert seen == {"system": SYSTEM, "user": USER, "max_tokens": 900}

    def test_an_anthropic_failure_arrives_as_an_aierror(self, monkeypatch, anthropic_only):
        def _down(system, user, *, max_tokens):
            raise AnthropicError("529 overloaded")

        monkeypatch.setattr(anthropic_llm, "generate", _down)
        with pytest.raises(AIError):
            ai_provider.generate(SYSTEM, USER, max_tokens=900)

    def test_an_unexpected_exception_never_escapes_raw(self, monkeypatch, anthropic_only):
        def _boom(system, user, *, max_tokens):
            raise KeyError("content")

        monkeypatch.setattr(anthropic_llm, "generate", _boom)
        with pytest.raises(AIError):
            ai_provider.generate(SYSTEM, USER, max_tokens=900)


class TestNothingConfigured:
    def test_the_error_names_no_variable_but_the_log_does(self, monkeypatch, caplog):
        monkeypatch.setattr(ai_provider.settings, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(ai_provider.settings, "LLM_API_KEY", "")
        with caplog.at_level(logging.ERROR, logger="app.services.ai_provider"):
            with pytest.raises(AIError) as excinfo:
                ai_provider.generate(SYSTEM, USER, max_tokens=500)
        assert str(excinfo.value) == ai_provider.NOT_CONFIGURED_MESSAGE
        assert "ANTHROPIC_API_KEY" not in str(excinfo.value)
        assert "LLM_API_KEY" not in str(excinfo.value)
        assert "ANTHROPIC_API_KEY" in caplog.text and "LLM_API_KEY" in caplog.text


class TestOutputTokenCapAlias:
    def test_the_old_anthropic_name_still_sets_the_cap(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_MAX_OUTPUT_TOKENS", "321")
        monkeypatch.delenv("AI_MAX_OUTPUT_TOKENS", raising=False)
        assert Settings(_env_file=None, DATABASE_URL="sqlite://").AI_MAX_OUTPUT_TOKENS == 321

    def test_the_new_name_wins_when_both_are_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_MAX_OUTPUT_TOKENS", "321")
        monkeypatch.setenv("AI_MAX_OUTPUT_TOKENS", "654")
        assert Settings(_env_file=None, DATABASE_URL="sqlite://").AI_MAX_OUTPUT_TOKENS == 654

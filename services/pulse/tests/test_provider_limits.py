"""The failure this module exists for: a user indexed several repositories and one came
back as "the embedding service is unavailable", when OpenAI had said

    429 Rate limit reached for text-embedding-3-small on tokens per min (TPM):
    Limit 1000000, Used 1000000, Requested 46142. Please try again in 2.768s.

Three seconds, named to the millisecond, and the run was discarded.
"""
import pytest
from app.config import settings
from app.services import embeddings
from app.services.provider_limits import (
    ProviderRateLimited, call_with_retry, is_rate_limit, wait_seconds_for,
)


class FakeResponse:
    def __init__(self, status_code=429, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class RateLimitError(Exception):
    """Named as the provider SDKs name it, which is one of the three things is_rate_limit
    looks at."""

    def __init__(self, message="rate limited", headers=None, status_code=429):
        super().__init__(message)
        self.status_code = status_code
        self.response = FakeResponse(status_code, headers)


class Recorder:
    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)


class TestRecognisingARateLimit:
    def test_the_providers_own_exception_name_is_enough(self):
        class RateLimitError(Exception):
            pass

        assert is_rate_limit(RateLimitError("429")) is True

    def test_a_status_code_on_the_exception_counts(self):
        exc = Exception("boom")
        exc.status_code = 429
        assert is_rate_limit(exc) is True

    def test_a_status_code_on_the_response_counts(self):
        exc = Exception("boom")
        exc.response = FakeResponse(429)
        assert is_rate_limit(exc) is True

    @pytest.mark.parametrize("status", [400, 401, 500, 503])
    def test_anything_else_is_not_a_rate_limit(self, status):
        exc = Exception("boom")
        exc.response = FakeResponse(status)
        assert is_rate_limit(exc) is False

    def test_an_ordinary_exception_is_not_a_rate_limit(self):
        assert is_rate_limit(ValueError("nope")) is False


class TestReadingTheWait:
    def test_the_real_openai_message_is_understood(self):
        message = (
            "Rate limit reached for text-embedding-3-small in organization org-x on tokens "
            "per min (TPM): Limit 1000000, Used 1000000, Requested 46142. "
            "Please try again in 2.768s. Visit https://platform.openai.com/account/rate-limits"
        )
        assert wait_seconds_for(RateLimitError(message)) == pytest.approx(2.768)

    @pytest.mark.parametrize("message,expected", [
        ("Please try again in 20s.", 20.0),
        ("Please try again in 500ms.", 0.5),
        ("please try again in 1m20s", 80.0),
        ("Retry after 30 seconds", 30.0),
    ])
    def test_the_shapes_the_providers_use(self, message, expected):
        assert wait_seconds_for(RateLimitError(message)) == pytest.approx(expected)

    def test_a_retry_after_header_wins_over_the_message(self):
        exc = RateLimitError("Please try again in 2.768s.", headers={"retry-after": "9"})
        assert wait_seconds_for(exc) == 9.0

    def test_a_millisecond_header_is_read_as_seconds(self):
        assert wait_seconds_for(RateLimitError("no hint", headers={"retry-after-ms": "2768"})) == pytest.approx(2.768)

    def test_a_reset_header_is_read_when_there_is_nothing_else(self):
        assert wait_seconds_for(RateLimitError("no hint", headers={"x-ratelimit-reset-tokens": "6s"})) == 6.0

    def test_a_header_that_is_not_a_number_falls_through_to_the_message(self):
        exc = RateLimitError("Please try again in 4s.", headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert wait_seconds_for(exc) == 4.0

    def test_silence_is_reported_as_silence(self):
        assert wait_seconds_for(RateLimitError("rate limited, no further detail")) is None


class TestWaitingItOut:
    def test_it_waits_exactly_what_the_provider_asked_and_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        sleep = Recorder()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError("Please try again in 2.768s.")
            return "answer"

        assert call_with_retry(flaky, label="embeddings", sleep=sleep) == "answer"
        assert sleep.slept == [pytest.approx(2.768)]
        assert calls["n"] == 2

    def test_it_tries_more_than_twice(self, monkeypatch):
        """The bug was one flat retry. Several short waits in a row have to be survivable."""
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        monkeypatch.setattr(settings, "PROVIDER_MAX_RETRIES", 4)
        sleep = Recorder()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 4:
                raise RateLimitError("Please try again in 3s.")
            return "answer"

        assert call_with_retry(flaky, label="embeddings", sleep=sleep) == "answer"
        assert sleep.slept == [3.0, 3.0, 3.0]

    def test_with_no_hint_it_backs_off_instead_of_hammering(self, monkeypatch):
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        monkeypatch.setattr(settings, "PROVIDER_MAX_RETRIES", 4)
        sleep = Recorder()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RateLimitError("rate limited, no further detail")
            return "answer"

        assert call_with_retry(flaky, label="OpenAI", sleep=sleep) == "answer"
        assert sleep.slept == [2.0, 4.0]

    def test_one_long_wait_is_refused_rather_than_pinning_a_worker(self, monkeypatch):
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        sleep = Recorder()

        with pytest.raises(ProviderRateLimited) as caught:
            call_with_retry(lambda: (_ for _ in ()).throw(RateLimitError("Please try again in 1800s.")), label="embeddings", sleep=sleep)

        assert sleep.slept == []
        assert caught.value.wait_seconds == 1800.0
        assert "rate limited" in str(caught.value)

    def test_short_waits_are_refused_once_they_add_up(self, monkeypatch):
        """A provider throttling every few seconds must not hold a worker for ever by
        never asking for long."""
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 10)
        monkeypatch.setattr(settings, "PROVIDER_MAX_RETRIES", 20)
        sleep = Recorder()

        with pytest.raises(ProviderRateLimited):
            call_with_retry(lambda: (_ for _ in ()).throw(RateLimitError("Please try again in 4s.")), label="embeddings", sleep=sleep)

        assert sleep.slept == [4.0, 4.0]
        assert sum(sleep.slept) <= 10

    def test_it_gives_up_after_the_attempt_limit(self, monkeypatch):
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 600)
        monkeypatch.setattr(settings, "PROVIDER_MAX_RETRIES", 2)
        sleep = Recorder()

        with pytest.raises(ProviderRateLimited):
            call_with_retry(lambda: (_ for _ in ()).throw(RateLimitError("Please try again in 1s.")), label="embeddings", sleep=sleep)

        assert sleep.slept == [1.0, 1.0]

    def test_anything_that_is_not_a_rate_limit_is_raised_at_once(self, monkeypatch):
        """Retrying a rejected key or a malformed request makes the same mistake slower."""
        sleep = Recorder()

        with pytest.raises(ValueError):
            call_with_retry(lambda: (_ for _ in ()).throw(ValueError("bad request")), label="embeddings", sleep=sleep)

        assert sleep.slept == []

    def test_a_call_that_works_first_time_never_sleeps(self):
        sleep = Recorder()
        assert call_with_retry(lambda: 7, label="embeddings", sleep=sleep) == 7
        assert sleep.slept == []


class TestEmbeddingsUseIt:
    def _client(self, failures, message="Please try again in 2.768s."):
        class Embeddings:
            def __init__(self):
                self.calls = 0

            def create(self, model, input):
                self.calls += 1
                if self.calls <= failures:
                    raise RateLimitError(message)
                return type("Resp", (), {
                    "data": [type("Row", (), {"index": i, "embedding": [0.1, 0.2]})() for i in range(len(input))],
                    "usage": type("U", (), {"total_tokens": 11})(),
                })()

        return type("Client", (), {"embeddings": Embeddings()})()

    def test_a_transient_limit_is_waited_out_rather_than_failing_the_batch(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-x")
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 60)
        client = self._client(failures=1)
        monkeypatch.setattr(embeddings, "_build_client", lambda credential=None: client)
        monkeypatch.setattr("app.services.provider_limits.time.sleep", lambda s: None)

        vectors, tokens = embeddings.embed_texts(["one", "two"])

        assert len(vectors) == 2 and tokens == 11

    def test_a_limit_too_long_to_wait_out_is_not_reported_as_an_outage(self, monkeypatch):
        """EmbeddingError means the service is broken and the work is lost.
        ProviderRateLimited means come back, and the caller keeps what it has."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-x")
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 5)
        client = self._client(failures=99, message="Please try again in 1800s.")
        monkeypatch.setattr(embeddings, "_build_client", lambda credential=None: client)

        with pytest.raises(ProviderRateLimited):
            embeddings.embed_texts(["one"])

    def test_a_real_failure_is_still_an_embedding_error(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-x")

        class Broken:
            class embeddings:
                @staticmethod
                def create(model, input):
                    raise ValueError("connection reset")

        monkeypatch.setattr(embeddings, "_build_client", lambda credential=None: Broken())
        monkeypatch.setattr("app.services.embeddings.time.sleep", lambda s: None)

        with pytest.raises(embeddings.EmbeddingError):
            embeddings.embed_texts(["one"])


class TestProviderModulesPassItThrough:
    """Every generation path has to let ProviderRateLimited past rather than flattening
    it into "generation failed". A caller that cannot tell busy from broken retries the
    wrong thing."""

    def _limited_client(self, attr_path):
        def create(*args, **kwargs):
            raise RateLimitError("Please try again in 1800s.")

        return create

    def test_ai_provider_openai_lets_it_through(self, monkeypatch):
        from app.services import ai_provider

        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 5)
        monkeypatch.setattr(ai_provider, "_call_openai_once", self._limited_client(None))
        monkeypatch.setattr(ai_provider, "_build_openai_client", lambda credential=None: object())

        with pytest.raises(ProviderRateLimited):
            ai_provider._via_openai("s", "u", max_tokens=10)

    def test_ai_provider_anthropic_lets_it_through(self, monkeypatch):
        from app.services import ai_provider, anthropic_llm

        def limited(system, user, *, max_tokens, **kwargs):
            raise ProviderRateLimited(1800.0, "Anthropic")

        monkeypatch.setattr(anthropic_llm, "generate", limited)

        with pytest.raises(ProviderRateLimited):
            ai_provider._via_anthropic("s", "u", max_tokens=10)

    def test_anthropic_llm_lets_it_through(self, monkeypatch):
        from app.services import anthropic_llm

        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 5)
        monkeypatch.setattr(anthropic_llm, "_build_client", lambda api_key=None: object())
        monkeypatch.setattr(anthropic_llm, "_call_once", self._limited_client(None))

        with pytest.raises(ProviderRateLimited):
            anthropic_llm.generate("s", "u", max_tokens=10)

    def test_llm_summaries_lets_it_through(self, monkeypatch):
        from app.services import llm

        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-x")
        monkeypatch.setattr(settings, "PROVIDER_MAX_WAIT_SECONDS", 5)
        monkeypatch.setattr(llm, "_build_client", lambda credential=None: object())
        monkeypatch.setattr(llm, "_call_once", self._limited_client(None))

        with pytest.raises(ProviderRateLimited):
            llm.generate_summaries({"week_start": "2026-07-06"})

    def test_a_real_failure_is_still_a_wrapped_error(self, monkeypatch):
        from app.services import ai_provider

        monkeypatch.setattr(ai_provider, "_build_openai_client", lambda credential=None: object())
        monkeypatch.setattr(ai_provider, "_call_openai_once", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
        monkeypatch.setattr("app.services.ai_provider.time.sleep", lambda s: None)

        with pytest.raises(ai_provider.AIError):
            ai_provider._via_openai("s", "u", max_tokens=10)

import pytest
from app.config import settings
from app.services import embeddings
from app.services.embeddings import EmbeddingError


class FakeUsage:

    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class FakeRow:

    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


class FakeResponse:

    def __init__(self, rows, tokens=10):
        self.data = rows
        self.usage = FakeUsage(tokens)


class FakeEmbeddings:

    def __init__(self, recorder, responder):
        self._rec = recorder
        self._responder = responder

    def create(self, *, model, input):
        self._rec.append({"model": model, "input": list(input)})
        return self._responder(list(input), len(self._rec))


class FakeClient:

    def __init__(self, recorder, responder):
        self.embeddings = FakeEmbeddings(recorder, responder)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(embeddings.time, "sleep", lambda _seconds: None)


def _install(monkeypatch, responder):
    calls: list[dict] = []
    monkeypatch.setattr(embeddings, "_build_client", lambda credential=None: FakeClient(calls, responder))
    return calls


def _numbered(batch, _attempt):
    return FakeResponse([FakeRow(i, [float(i)] * 3) for i in range(len(batch))], tokens=len(batch))


def test_no_key_is_a_configuration_error_that_names_nothing_internal(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    with pytest.raises(EmbeddingError) as exc:
        embeddings.embed_texts(["hello"])

    assert "LLM_API_KEY" not in str(exc.value)
    assert "not set up" in str(exc.value)


def test_no_texts_never_calls_the_provider(monkeypatch):
    calls = _install(monkeypatch, _numbered)

    assert embeddings.embed_texts([]) == ([], 0)
    assert calls == []


def test_texts_are_batched_and_tokens_summed(monkeypatch):
    monkeypatch.setattr(settings, "INDEX_EMBED_BATCH_SIZE", 2)
    calls = _install(monkeypatch, _numbered)

    vectors, tokens = embeddings.embed_texts(["a", "b", "c", "d", "e"])

    assert [len(c["input"]) for c in calls] == [2, 2, 1]
    assert len(vectors) == 5
    assert tokens == 5
    assert calls[0]["model"] == settings.EMBEDDING_MODEL


def test_vectors_come_back_in_input_order_even_when_the_response_is_shuffled(monkeypatch):
    def shuffled(batch, _attempt):
        rows = [FakeRow(i, [float(i)]) for i in range(len(batch))]
        return FakeResponse(list(reversed(rows)))

    _install(monkeypatch, shuffled)

    vectors, _ = embeddings.embed_texts(["a", "b", "c"])

    assert vectors == [[0.0], [1.0], [2.0]]


def test_one_failure_is_retried_and_then_succeeds(monkeypatch, no_sleep):
    def flaky(batch, attempt):
        if attempt == 1:
            raise RuntimeError("provider hiccup")
        return _numbered(batch, attempt)

    calls = _install(monkeypatch, flaky)

    vectors, _ = embeddings.embed_texts(["a"])

    assert len(calls) == 2
    assert len(vectors) == 1


def test_a_second_failure_becomes_an_embedding_error(monkeypatch, no_sleep):
    def always_fails(_batch, _attempt):
        raise RuntimeError("provider down")

    calls = _install(monkeypatch, always_fails)

    with pytest.raises(EmbeddingError):
        embeddings.embed_texts(["a"])

    assert len(calls) == 2


def test_a_short_response_is_refused_rather_than_misfiled(monkeypatch):
    def short(_batch, _attempt):
        return FakeResponse([FakeRow(0, [1.0])])

    _install(monkeypatch, short)

    with pytest.raises(EmbeddingError) as exc:
        embeddings.embed_texts(["a", "b"])

    assert "2 inputs" in str(exc.value)


def test_missing_usage_counts_as_zero_tokens_rather_than_failing(monkeypatch):
    def no_usage(batch, _attempt):
        resp = FakeResponse([FakeRow(i, [float(i)]) for i in range(len(batch))])
        resp.usage = None
        return resp

    _install(monkeypatch, no_usage)

    vectors, tokens = embeddings.embed_texts(["a"])

    assert len(vectors) == 1 and tokens == 0


def test_the_real_client_is_only_built_when_a_key_exists(monkeypatch):
    """_build_client imports openai inside the function, so a missing package or key can
    never break import of this module (or the CI import check)."""
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test")

    client = embeddings._build_client()

    assert client is not None

from collections.abc import Mapping
from pathlib import Path

import pytest

from rag_eval.hashing import JSONValue
from rag_eval.llm.budget import BudgetExceededError, BudgetGuard
from rag_eval.llm.cache import CacheError, ResponseCache, cache_key
from rag_eval.llm.client import ModelClient, ModelError
from rag_eval.llm.transport import TransportError
from rag_eval.llm.types import (
    ChatRequest,
    EmbeddingRequest,
    Message,
    ModelPrice,
    Role,
    Usage,
)

PRICES = {"cheap/model": ModelPrice(input_per_million=1.0, output_per_million=2.0)}


def _chat_body(
    text: str = "an answer", *, finish: str = "stop", provider: str = "acme"
) -> JSONValue:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        "provider": provider,
    }


class FakeTransport:
    """A scripted transport. Records every request it is given."""

    def __init__(self, responses: list[tuple[int, JSONValue]] | None = None) -> None:
        self.responses = responses or [(200, _chat_body())]
        self.requests: list[JSONValue] = []
        self.calls = 0

    def post(
        self, url: str, headers: Mapping[str, str], payload: JSONValue, timeout: float
    ) -> tuple[int, JSONValue]:
        self.requests.append(payload)
        self.calls += 1
        index = min(self.calls - 1, len(self.responses) - 1)
        outcome = self.responses[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ExplodingTransport:
    """A transport that cannot reach the network at all."""

    def __init__(self) -> None:
        self.calls = 0

    def post(
        self, url: str, headers: Mapping[str, str], payload: JSONValue, timeout: float
    ) -> tuple[int, JSONValue]:
        self.calls += 1
        raise TransportError("no route to host")


def _client(
    tmp_path: Path,
    transport: object,
    *,
    limit_usd: float = 1.0,
    max_attempts: int = 3,
) -> ModelClient:
    return ModelClient(
        transport=transport,  # type: ignore[arg-type]
        cache=ResponseCache(tmp_path / "cache"),
        budget=BudgetGuard(limit_usd),
        prices=PRICES,
        api_key="test-key",
        max_attempts=max_attempts,
        backoff_seconds=0.0,
        sleep=lambda _seconds: None,
    )


def _request(**overrides: object) -> ChatRequest:
    base: dict[str, object] = {
        "model": "cheap/model",
        "messages": (Message(role=Role.USER, content="Which law governs?"),),
        "prompt_version": "v1",
    }
    return ChatRequest.model_validate(base | overrides)


# --- cache keys: the most dangerous thing in this module ----------------------


def test_identical_requests_share_a_key() -> None:
    assert cache_key("chat", _request()) == cache_key("chat", _request())


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other/model"},
        {"prompt_version": "v2"},
        {"temperature": 0.7},
        {"max_output_tokens": 1024},
        {"provider": "acme"},
        {"messages": (Message(role=Role.USER, content="A different question?"),)},
    ],
)
def test_every_field_that_can_change_an_answer_changes_the_key(change: dict[str, object]) -> None:
    """A field that alters the output but not the key would serve a stale answer
    under a new configuration's name, with nothing about it looking wrong."""
    assert cache_key("chat", _request()) != cache_key("chat", _request(**change))


def test_chat_and_embedding_requests_never_collide() -> None:
    chat = cache_key("chat", _request())
    embedding = cache_key("embedding", EmbeddingRequest(model="cheap/model", inputs=("x",)))

    assert chat != embedding


# --- caching behaviour --------------------------------------------------------


def test_second_identical_call_is_served_from_cache(tmp_path: Path) -> None:
    transport = FakeTransport()
    client = _client(tmp_path, transport)

    first = client.chat(_request())
    second = client.chat(_request())

    assert transport.calls == 1, "the second call must not reach the network"
    assert first.text == second.text
    assert first.record.cache_hit is False
    assert second.record.cache_hit is True
    assert second.record.cost_usd == 0.0


def test_a_changed_prompt_version_misses_the_cache(tmp_path: Path) -> None:
    transport = FakeTransport([(200, _chat_body("first")), (200, _chat_body("second"))])
    client = _client(tmp_path, transport)

    client.chat(_request())
    result = client.chat(_request(prompt_version="v2"))

    assert transport.calls == 2
    assert result.text == "second"


def test_a_corrupt_cache_entry_is_an_error_not_a_miss(tmp_path: Path) -> None:
    """Treating it as a miss would silently re-spend money and hide the corruption."""
    cache = ResponseCache(tmp_path / "cache")
    key = cache_key("chat", _request())
    path = cache.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CacheError, match="could not be read"):
        cache.get(key)


# --- cost and budget ----------------------------------------------------------


def test_cost_is_computed_from_the_price_table(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport())

    record = client.chat(_request()).record

    assert record.usage == Usage(prompt_tokens=1000, completion_tokens=500)
    assert record.cost_usd == pytest.approx((1000 * 1.0 + 500 * 2.0) / 1_000_000)


def test_the_run_stops_at_its_spending_limit(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport(), limit_usd=0.0000015)

    client.chat(_request())
    with pytest.raises(BudgetExceededError) as caught:
        client.chat(_request(prompt_version="v2"))

    assert caught.value.calls >= 1
    assert "Results up to this point are complete" in str(caught.value)


def test_a_cached_call_costs_nothing_but_still_counts(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport())

    client.chat(_request())
    spent_after_first = client.spent_usd
    client.chat(_request())

    assert client.spent_usd == spent_after_first
    assert client.budget.calls == 2


def test_a_zero_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        BudgetGuard(0.0)


# --- retries ------------------------------------------------------------------


def test_a_rate_limit_is_retried_and_the_attempts_are_recorded(tmp_path: Path) -> None:
    transport = FakeTransport([(429, {"error": "slow down"}), (200, _chat_body())])
    client = _client(tmp_path, transport)

    record = client.chat(_request()).record

    assert transport.calls == 2
    assert record.attempts == 2, "a retry that is not counted hides an unstable provider"


def test_a_bad_request_is_not_retried(tmp_path: Path) -> None:
    """Repeating a malformed request only wastes time and money."""
    transport = FakeTransport([(400, {"error": {"message": "bad model"}})])
    client = _client(tmp_path, transport)

    with pytest.raises(ModelError, match="bad model"):
        client.chat(_request())

    assert transport.calls == 1


def test_giving_up_records_the_failure(tmp_path: Path) -> None:
    client = _client(tmp_path, ExplodingTransport(), max_attempts=2)

    with pytest.raises(ModelError, match="no route to host"):
        client.chat(_request())

    assert client.records[-1].error is not None
    assert client.records[-1].cache_hit is False


def test_a_failed_call_is_not_cached(tmp_path: Path) -> None:
    transport = FakeTransport([(500, {"error": "boom"}), (200, _chat_body("recovered"))])
    client = _client(tmp_path, transport, max_attempts=1)

    with pytest.raises(ModelError):
        client.chat(_request())
    assert client.chat(_request()).text == "recovered"


# --- honesty about what came back ---------------------------------------------


def test_a_truncated_answer_is_recorded_as_truncated(tmp_path: Path) -> None:
    """An answer cut off at the limit must never be scored as if the model chose to stop."""
    client = _client(tmp_path, FakeTransport([(200, _chat_body("cut off half", finish="length"))]))

    assert client.chat(_request()).record.truncated is True


def test_a_complete_answer_is_not_marked_truncated(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport())

    assert client.chat(_request()).record.truncated is False


def test_the_serving_provider_is_recorded(tmp_path: Path) -> None:
    """A gateway that silently switches provider would make deltas unattributable."""
    client = _client(tmp_path, FakeTransport([(200, _chat_body(provider="somewhere-else"))]))

    record = client.chat(_request(provider="acme")).record

    assert record.provider_requested == "acme"
    assert record.provider_served == "somewhere-else"


def test_pinning_a_provider_disables_fallback(tmp_path: Path) -> None:
    transport = FakeTransport()
    client = _client(tmp_path, transport)

    client.chat(_request(provider="acme"))

    sent = transport.requests[0]
    assert isinstance(sent, dict)
    assert sent["provider"] == {"order": ["acme"], "allow_fallbacks": False}


def test_a_response_without_content_is_an_error(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport([(200, {"choices": []})]))

    with pytest.raises(ModelError, match="no choices"):
        client.chat(_request())


# --- embeddings ---------------------------------------------------------------


def _embedding_body(count: int, *, dims: int = 3) -> JSONValue:
    return {
        "data": [{"index": i, "embedding": [float(i)] * dims} for i in reversed(range(count))],
        "usage": {"prompt_tokens": 100},
        "provider": "acme",
    }


def test_embeddings_come_back_in_input_order(tmp_path: Path) -> None:
    """The gateway may return them in any order; misalignment would corrupt every vector."""
    client = _client(tmp_path, FakeTransport([(200, _embedding_body(3))]))

    result = client.embed(EmbeddingRequest(model="cheap/model", inputs=("a", "b", "c")))

    assert [vector[0] for vector in result.vectors] == [0.0, 1.0, 2.0]


def test_a_missing_embedding_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeTransport([(200, _embedding_body(2))]))

    with pytest.raises(ModelError, match="misaligned"):
        client.embed(EmbeddingRequest(model="cheap/model", inputs=("a", "b", "c")))


def test_embeddings_are_cached_too(tmp_path: Path) -> None:
    transport = FakeTransport([(200, _embedding_body(1))])
    client = _client(tmp_path, transport)
    request = EmbeddingRequest(model="cheap/model", inputs=("only",))

    client.embed(request)
    client.embed(request)

    assert transport.calls == 1


# --- credentials --------------------------------------------------------------


def test_a_missing_key_fails_only_when_a_call_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing this package on a machine with no credentials must work."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = ModelClient(
        transport=FakeTransport(),
        cache=ResponseCache(tmp_path / "cache"),
        budget=BudgetGuard(1.0),
        prices=PRICES,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(ModelError, match="no API key"):
        client.chat(_request())

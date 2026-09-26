"""The single place every model call passes through.

Nothing else in this project talks to a model. That is what makes the model choice a
configuration value rather than an architectural commitment (D-005), and it is the
one boundary the test suite mocks, which is how the whole suite runs with no network
and no credentials.

What this layer guarantees, and why each one matters:

* **Caching**, keyed on everything that can change an answer. A rerun during
  development costs nothing and returns the same text.
* **A hard spending limit**, checked before every call. At ₹1000 total, a retry loop
  is not an inconvenience.
* **Explicit retries**, only on failures that are worth retrying, each one counted
  and reported. A silent retry hides an unstable provider.
* **Provider pinning**, because a gateway that routes the same model name to
  different providers would make a score difference impossible to attribute.
* **Truncation reported, never hidden.** An answer cut off at the output limit is
  recorded as truncated, so it is never scored as though the model chose to stop.
"""

from __future__ import annotations

import base64
import binascii
import os
import struct
import time
from collections.abc import Sequence

from rag_eval.errors import RagEvalError
from rag_eval.hashing import JSONValue
from rag_eval.llm.budget import BudgetGuard
from rag_eval.llm.cache import ResponseCache, cache_key
from rag_eval.llm.transport import Transport, TransportError
from rag_eval.llm.types import (
    CallRecord,
    ChatRequest,
    ChatResult,
    EmbeddingRequest,
    EmbeddingResult,
    ModelPrice,
    Usage,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_VARIABLE = "OPENROUTER_API_KEY"

RETRYABLE_CLIENT_STATUSES = frozenset({408, 409, 429})
"""The 4xx statuses worth trying again: a timeout, a conflict and a rate limit. Any
other 4xx means the request itself is wrong, and repeating it wastes time and money."""


def is_retryable(status: int) -> bool:
    """Whether a failed status is worth trying again.

    Every 5xx is an upstream fault and retried, except 501 (the server does not
    support the request at all). That includes the non-standard 520-524 that
    Cloudflare returns when the host behind it fails, which the gateway passes on.
    """
    return status in RETRYABLE_CLIENT_STATUSES or (500 <= status <= 599 and status != 501)


class ModelError(RagEvalError):
    """A model call failed in a way the caller has to know about."""


class UnpricedModelError(ModelError):
    """The model has no known price, so the spending limit cannot account for it.

    Refused before any network call. The alternative - treating an unknown price as
    zero - once made every embedding call invisible to the spending limit.
    """


class MissingCredentialsError(ModelError):
    """No API key was available.

    Raised when a call is attempted, never at import time, so that importing this
    package on a machine with no credentials still works — which the test suite
    depends on.
    """


class ModelClient:
    """Calls chat and embedding models through an OpenAI-compatible gateway."""

    def __init__(
        self,
        *,
        transport: Transport,
        cache: ResponseCache,
        budget: BudgetGuard,
        prices: dict[str, ModelPrice],
        base_url: str = OPENROUTER_BASE_URL,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
        sleep: object = time.sleep,
    ) -> None:
        """Assemble a client. The API key is read lazily, on first call."""
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        self.transport = transport
        self.cache = cache
        self.budget = budget
        self.prices = prices
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self.records: list[CallRecord] = []

    # -- public API ----------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResult:
        """Send a chat request and return its answer.

        Raises:
            ModelError: if the call failed after every attempt.
            BudgetExceeded: if the run has reached its spending limit.
        """
        body, record = self._call(
            kind="chat",
            request=request,
            path="/chat/completions",
            payload=self._chat_payload(request),
        )
        text, truncated = _read_chat_body(body)
        record = record.model_copy(update={"truncated": truncated})
        self.records.append(record)
        return ChatResult(text=text, record=record)

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        """Embed one or more texts.

        Raises:
            ModelError: if the call failed, or returned a different number of vectors
                than texts given — which would silently misalign every vector after it.
            BudgetExceeded: if the run has reached its spending limit.
        """
        body, record = self._call(
            kind="embedding",
            request=request,
            path="/embeddings",
            payload=self._embedding_payload(request),
        )
        vectors = _read_embedding_body(body, expected=len(request.inputs))
        self.records.append(record)
        return EmbeddingResult(vectors=vectors, record=record)

    @property
    def spent_usd(self) -> float:
        """What this client has spent so far."""
        return self.budget.spent_usd

    # -- internals -----------------------------------------------------------

    def _api_key_or_fail(self) -> str:
        key = self._api_key or os.environ.get(API_KEY_VARIABLE, "")
        if not key:
            raise MissingCredentialsError(
                f"no API key: set {API_KEY_VARIABLE} in your environment or .env file. "
                "Copy .env.example to .env and paste your key there."
            )
        return key

    def _chat_payload(self, request: ChatRequest) -> JSONValue:
        payload: dict[str, JSONValue] = {
            "model": request.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.provider:
            payload["provider"] = {
                "order": [request.provider],
                "allow_fallbacks": False,
            }
        return payload

    def _embedding_payload(self, request: EmbeddingRequest) -> JSONValue:
        payload: dict[str, JSONValue] = {
            "model": request.model,
            "input": list(request.inputs),
            # Base64-encoded float32 rather than a JSON list of decimals: about a third
            # of the size, which matters when a full index is 15,000 vectors held in
            # the response cache. A provider that ignores this and returns plain lists
            # is handled too - see _vector_of.
            "encoding_format": "base64",
        }
        if request.provider:
            payload["provider"] = {"order": [request.provider], "allow_fallbacks": False}
        return payload

    def _call(
        self, *, kind: str, request: ChatRequest | EmbeddingRequest, path: str, payload: JSONValue
    ) -> tuple[JSONValue, CallRecord]:
        """Serve a request from cache, or make it, retrying only what is worth retrying."""
        key = cache_key(kind, request)
        cached = self.cache.get(key)
        if cached is not None:
            record = CallRecord(
                model=request.model,
                kind=kind,
                cache_hit=True,
                attempts=1,
                provider_requested=request.provider,
                provider_served=_provider_of(cached),
                usage=_usage_of(cached),
                cost_usd=0.0,
            )
            self.budget.record(0.0)
            return cached, record

        price = self.prices.get(request.model)
        if price is None:
            raise UnpricedModelError(
                f"no price is known for {request.model}, so the spending limit cannot "
                "account for it. Check the model id, or add its price to "
                "configs/prices.yaml with a source and the date you checked it."
            )
        self.budget.check()
        started = time.monotonic()
        failures: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            try:
                status, body = self.transport.post(
                    f"{self.base_url}{path}",
                    {
                        "Authorization": f"Bearer {self._api_key_or_fail()}",
                        "HTTP-Referer": "https://github.com/AkshGoyal/Rag-Eval-Harness",
                        "X-Title": "rag-eval-harness",
                    },
                    payload,
                    self.timeout_seconds,
                )
            except TransportError as exc:
                failures.append(f"attempt {attempt}: {exc}")
                if attempt == self.max_attempts:
                    break
                self._wait(attempt)
                continue

            if status == 200:
                usage = _usage_of(body)
                cost = price.cost_of(usage) if usage is not None else 0.0
                self.budget.record(cost)
                # Only successful responses are cached. Caching a failure would make
                # a transient outage permanent for every later run.
                self.cache.put(key, body)
                return body, CallRecord(
                    model=request.model,
                    kind=kind,
                    cache_hit=False,
                    attempts=attempt,
                    provider_requested=request.provider,
                    provider_served=_provider_of(body),
                    usage=usage,
                    cost_usd=cost,
                    cost_known=usage is not None,
                    latency_seconds=round(time.monotonic() - started, 3),
                )

            failures.append(f"attempt {attempt}: HTTP {status} {_error_of(body)}")
            if not is_retryable(status) or attempt == self.max_attempts:
                break
            self._wait(attempt)

        detail = "; ".join(failures)
        self.records.append(
            CallRecord(
                model=request.model,
                kind=kind,
                cache_hit=False,
                attempts=len(failures) or 1,
                provider_requested=request.provider,
                latency_seconds=round(time.monotonic() - started, 3),
                error=detail,
            )
        )
        raise ModelError(f"{request.model} call failed after {len(failures)} attempt(s): {detail}")

    def _wait(self, attempt: int) -> None:
        """Back off before retrying, doubling each time."""
        delay = self.backoff_seconds * (2 ** (attempt - 1))
        sleeper = self._sleep
        if callable(sleeper):
            sleeper(delay)


# -- response reading --------------------------------------------------------


def _as_mapping(body: JSONValue) -> dict[str, JSONValue]:
    return body if isinstance(body, dict) else {}


def _provider_of(body: JSONValue) -> str | None:
    """Which upstream provider served the call, when the gateway says so."""
    value = _as_mapping(body).get("provider")
    return value if isinstance(value, str) else None


def _usage_of(body: JSONValue) -> Usage | None:
    raw = _as_mapping(body).get("usage")
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens", 0)
    if not isinstance(prompt, int):
        return None
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion if isinstance(completion, int) else 0,
    )


def _error_of(body: JSONValue) -> str:
    error = _as_mapping(body).get("error")
    if isinstance(error, dict):
        message = error.get("message")
        return str(message) if message is not None else str(error)
    return str(error) if error is not None else ""


def _read_chat_body(body: JSONValue) -> tuple[str, bool]:
    """Pull the answer text out, and note whether it was cut short."""
    choices = _as_mapping(body).get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelError("the response contained no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ModelError("the response's first choice is not an object")
    message = first.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ModelError("the response contained no message content")
    return content, first.get("finish_reason") == "length"


def _read_embedding_body(body: JSONValue, *, expected: int) -> tuple[tuple[float, ...], ...]:
    """Pull the vectors out, in the order the inputs were given."""
    data = _as_mapping(body).get("data")
    if not isinstance(data, list):
        raise ModelError("the response contained no embedding data")
    if len(data) != expected:
        raise ModelError(
            f"asked for {expected} embeddings and received {len(data)}; "
            "vectors would be misaligned with their texts"
        )
    return tuple(
        _vector_of(item.get("embedding"), position)
        for position, item in enumerate(_sorted_by_index(data))
    )


def _vector_of(raw: JSONValue, position: int) -> tuple[float, ...]:
    """Decode one embedding, whether it arrived as base64 float32 or a list of numbers."""
    if isinstance(raw, str):
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ModelError(f"embedding {position} is not valid base64: {exc}") from exc
        if not decoded or len(decoded) % 4:
            raise ModelError(
                f"embedding {position} decoded to {len(decoded)} bytes, "
                "which is not a whole number of 32-bit floats"
            )
        values = struct.unpack(f"<{len(decoded) // 4}f", decoded)
        return tuple(float(value) for value in values)
    if isinstance(raw, list) and raw:
        if not all(isinstance(value, int | float) for value in raw):
            raise ModelError(f"embedding {position} contains a non-numeric value")
        return tuple(float(value) for value in raw if isinstance(value, int | float))
    raise ModelError(f"embedding {position} is missing or empty")


def _sorted_by_index(data: Sequence[JSONValue]) -> list[dict[str, JSONValue]]:
    """Order vectors by the index the gateway assigned, not by arrival."""
    items = [item for item in data if isinstance(item, dict)]

    def position(item: dict[str, JSONValue]) -> int:
        value = item.get("index", 0)
        return value if isinstance(value, int) else 0

    return sorted(items, key=position)

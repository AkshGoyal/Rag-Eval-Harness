"""What a model call is, and what it produced.

Every model call in this project is described by one of these requests and answered
by one of these results. The result carries more than the model's output: which
provider actually served it, whether it came from the cache, how many attempts it
took, what it cost, and whether the output was cut short. Those are not diagnostics
to be turned on when something looks wrong — they are the evidence that a number in
a report came from where it claims to.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """Who is speaking in a chat message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """One turn of a conversation sent to a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    content: str


class ChatRequest(BaseModel):
    """Everything that determines a chat model's answer.

    Every field here is part of the cache key. If a field can change the output and
    is not in this model, the cache will return an answer produced under different
    conditions and label it as this one's — the failure mode D-005 exists to prevent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    messages: tuple[Message, ...] = Field(min_length=1)
    prompt_version: str = Field(
        min_length=1,
        description="Version of the prompt file these messages were built from.",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=512, ge=1)
    provider: str | None = Field(
        default=None,
        description=(
            "The upstream provider to pin to. OpenRouter routes a model name to "
            "whichever provider is cheapest or fastest otherwise, and providers differ "
            "in quantisation and behaviour — which would make a score difference "
            "impossible to attribute to a configuration change."
        ),
    )


class EmbeddingRequest(BaseModel):
    """Everything that determines an embedding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    provider: str | None = None


class Usage(BaseModel):
    """Tokens consumed by one call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        """Prompt and completion tokens combined."""
        return self.prompt_tokens + self.completion_tokens


class ModelPrice(BaseModel):
    """What a model costs, in US dollars per million tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million: float = Field(ge=0.0)
    output_per_million: float = Field(default=0.0, ge=0.0)

    def cost_of(self, usage: Usage) -> float:
        """Cost in US dollars of the tokens in ``usage``."""
        return (
            usage.prompt_tokens * self.input_per_million
            + usage.completion_tokens * self.output_per_million
        ) / 1_000_000


class CallRecord(BaseModel):
    """The audit trail for one model call.

    Recorded whether the call succeeded or failed, and kept alongside results so that
    any reported number can be traced to the calls that produced it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    kind: str = Field(description="'chat' or 'embedding'.")
    cache_hit: bool
    attempts: int = Field(ge=1, description="1 means it succeeded first time.")
    provider_requested: str | None = None
    provider_served: str | None = Field(
        default=None, description="Who actually served it, as reported by the gateway."
    )
    usage: Usage | None = None
    cost_usd: float = Field(default=0.0, ge=0.0)
    truncated: bool = Field(
        default=False,
        description="The model stopped because it hit the output limit, not because it finished.",
    )
    latency_seconds: float = Field(default=0.0, ge=0.0)
    error: str | None = None


class ChatResult(BaseModel):
    """A chat model's answer, with the record of how it was obtained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    record: CallRecord


class EmbeddingResult(BaseModel):
    """Vectors, one per input, with the record of how they were obtained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vectors: tuple[tuple[float, ...], ...]
    record: CallRecord

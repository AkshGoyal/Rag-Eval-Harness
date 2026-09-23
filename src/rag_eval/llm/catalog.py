"""Asking the gateway what models it has, and what they cost.

Prices written into a document go stale, and prices carried in someone's head go
wrong. This reads them from the gateway at the moment they matter, so the cost a run
reports is computed from the rates actually in force rather than from a figure
someone copied down once.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rag_eval.errors import RagEvalError
from rag_eval.hashing import JSONValue
from rag_eval.llm.transport import Transport, TransportError
from rag_eval.llm.types import ModelPrice


class CatalogError(RagEvalError):
    """The model catalogue could not be read."""


class ModelInfo(BaseModel):
    """One model the gateway offers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    name: str = ""
    context_length: int = Field(default=0, ge=0)
    price: ModelPrice

    @property
    def is_free(self) -> bool:
        """Whether the gateway charges nothing for it. Free tiers are rate-limited."""
        return self.price.input_per_million == 0.0 and self.price.output_per_million == 0.0


def fetch_catalog(
    transport: Transport,
    *,
    base_url: str,
    api_key: str | None = None,
    timeout_seconds: float = 60.0,
) -> tuple[ModelInfo, ...]:
    """Read the gateway's model list.

    Raises:
        CatalogError: if the gateway cannot be reached or returns an unusable body.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        status, body = transport.get(f"{base_url.rstrip('/')}/models", headers, timeout_seconds)
    except TransportError as exc:
        raise CatalogError(str(exc)) from exc
    if status != 200:
        raise CatalogError(f"the gateway returned HTTP {status} for its model list")

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise CatalogError("the model list did not contain a 'data' array")

    models = [parsed for entry in data if (parsed := _parse(entry)) is not None]
    if not models:
        raise CatalogError("the model list was empty")
    return tuple(sorted(models, key=lambda model: model.model_id))


def fetch_embedding_catalog(
    transport: Transport,
    *,
    base_url: str,
    api_key: str | None = None,
    timeout_seconds: float = 60.0,
) -> tuple[tuple[ModelInfo, ...], str | None]:
    """Read the gateway's separate list of embedding models, if it has one.

    The main model list omits embedding models, so their prices have to come from
    here. Failure is reported rather than raised: the chat catalogue is still useful
    without it, and correctness does not depend on this call succeeding, because the
    client refuses any model it has no price for.

    Returns:
        The embedding models found, and a note explaining why none were, if none were.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        status, body = transport.get(
            f"{base_url.rstrip('/')}/embeddings/models", headers, timeout_seconds
        )
    except TransportError as exc:
        return (), f"embedding model list unreachable: {exc}"
    if status != 200:
        return (), f"embedding model list returned HTTP {status}"
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return (), "embedding model list had no 'data' array"
    models = tuple(
        sorted(
            (parsed for entry in data if (parsed := _parse(entry)) is not None),
            key=lambda model: model.model_id,
        )
    )
    return models, None if models else "embedding model list was empty"


def _parse(entry: JSONValue) -> ModelInfo | None:
    """Read one catalogue entry, skipping anything malformed rather than failing the lot."""
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None

    pricing = entry.get("pricing")
    pricing = pricing if isinstance(pricing, dict) else {}
    context = entry.get("context_length")
    name = entry.get("name")

    return ModelInfo(
        model_id=model_id,
        name=name if isinstance(name, str) else "",
        context_length=context if isinstance(context, int) else 0,
        # The gateway quotes dollars per token; everything else here is per million.
        price=ModelPrice(
            input_per_million=_per_million(pricing.get("prompt")),
            output_per_million=_per_million(pricing.get("completion")),
        ),
    )


def _per_million(value: JSONValue) -> float:
    """Convert a per-token price to per-million, tolerating a missing or odd value."""
    try:
        return max(0.0, float(str(value)) * 1_000_000) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def prices_from(catalog: tuple[ModelInfo, ...]) -> dict[str, ModelPrice]:
    """Index a catalogue by model id, for the client's cost accounting."""
    return {model.model_id: model.price for model in catalog}

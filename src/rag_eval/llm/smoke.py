"""Proving the model setup works, for a fraction of a rupee.

Before anything is built on top of a gateway, it is worth knowing that the key is
valid, the models exist, the provider pinning is honoured and the cost accounting is
right. This makes exactly two calls — one chat, one embedding — and prints what came
back, including which provider actually served each one.

It is deliberately separate from anything that produces results. Nothing it does is
cached into a run, and it writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag_eval.llm.budget import BudgetGuard
from rag_eval.llm.cache import ResponseCache
from rag_eval.llm.catalog import fetch_catalog, fetch_embedding_catalog, prices_from
from rag_eval.llm.client import ModelClient
from rag_eval.llm.prices import load_manual_prices, merge_prices
from rag_eval.llm.transport import Transport
from rag_eval.llm.types import CallRecord, ChatRequest, EmbeddingRequest, Message, Role


@dataclass(frozen=True)
class SmokeResult:
    """What the two test calls produced."""

    chat_text: str
    chat_record: CallRecord
    embedding_dimensions: int
    embedding_record: CallRecord
    catalogue_note: str | None = None

    @property
    def total_cost_usd(self) -> float:
        """What proving the setup cost."""
        return self.chat_record.cost_usd + self.embedding_record.cost_usd


def run_smoke_test(
    transport: Transport,
    *,
    base_url: str,
    chat_model: str,
    embedding_model: str,
    cache_dir: Path,
    api_key: str | None = None,
    provider: str | None = None,
    limit_usd: float = 0.05,
    manual_prices: Path = Path("configs/prices.yaml"),
) -> SmokeResult:
    """Make one chat call and one embedding call, and report everything about them.

    The spending limit is deliberately tiny. If these two calls somehow cost more
    than a few cents, something is wrong and the run should stop rather than continue.

    Raises:
        CatalogError: if the gateway's model list cannot be read.
        ModelError: if either call fails.
        BudgetExceededError: if the limit is reached, which would itself be a finding.
    """
    chat_models = fetch_catalog(transport, base_url=base_url, api_key=api_key)
    embedding_models, note = fetch_embedding_catalog(transport, base_url=base_url, api_key=api_key)
    prices = merge_prices(
        prices_from(chat_models + embedding_models), load_manual_prices(manual_prices)
    )
    client = ModelClient(
        transport=transport,
        cache=ResponseCache(cache_dir),
        budget=BudgetGuard(limit_usd),
        prices=prices,
        base_url=base_url,
        api_key=api_key,
    )

    chat = client.chat(
        ChatRequest(
            model=chat_model,
            messages=(
                Message(
                    role=Role.SYSTEM,
                    content="Answer in exactly one short sentence.",
                ),
                Message(
                    role=Role.USER,
                    content="What is the purpose of a governing law clause in a contract?",
                ),
            ),
            prompt_version="smoke-v1",
            max_output_tokens=60,
            provider=provider,
        )
    )
    embedding = client.embed(
        EmbeddingRequest(
            model=embedding_model,
            inputs=("This Agreement shall be governed by the laws of Delaware.",),
            provider=provider,
        )
    )

    return SmokeResult(
        chat_text=chat.text.strip(),
        chat_record=chat.record,
        embedding_dimensions=len(embedding.vectors[0]),
        embedding_record=embedding.record,
        catalogue_note=note,
    )

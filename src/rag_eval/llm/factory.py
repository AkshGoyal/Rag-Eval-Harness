"""Assembling a model client with every price it needs.

Kept in one place so that the setup check, index building and, later, generation all
price their calls the same way: the gateway's live catalogue first, its separate
embedding list second, and the hand-maintained price file only for what neither
covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rag_eval.llm.budget import BudgetGuard
from rag_eval.llm.cache import ResponseCache
from rag_eval.llm.catalog import fetch_catalog, fetch_embedding_catalog, prices_from
from rag_eval.llm.client import OPENROUTER_BASE_URL, ModelClient
from rag_eval.llm.prices import load_manual_prices, merge_prices
from rag_eval.llm.transport import Transport
from rag_eval.llm.types import ModelPrice

DEFAULT_PRICE_FILE = Path("configs/prices.yaml")


@dataclass(frozen=True)
class PricedClient:
    """A client, and a note if the embedding list could not be read."""

    client: ModelClient
    prices: dict[str, ModelPrice]
    catalogue_note: str | None


def build_client(
    transport: Transport,
    *,
    cache_dir: Path,
    limit_usd: float,
    api_key: str | None,
    base_url: str = OPENROUTER_BASE_URL,
    price_file: Path = DEFAULT_PRICE_FILE,
) -> PricedClient:
    """Read every price source and return a client that knows them all.

    Raises:
        CatalogError: if the gateway's main model list cannot be read.
        ConfigError: if the price file is malformed.
    """
    chat_models = fetch_catalog(transport, base_url=base_url, api_key=api_key)
    embedding_models, note = fetch_embedding_catalog(transport, base_url=base_url, api_key=api_key)
    prices = merge_prices(
        prices_from(chat_models + embedding_models), load_manual_prices(price_file)
    )
    client = ModelClient(
        transport=transport,
        cache=ResponseCache(cache_dir),
        budget=BudgetGuard(limit_usd),
        prices=prices,
        base_url=base_url,
        api_key=api_key,
    )
    return PricedClient(client=client, prices=prices, catalogue_note=note)

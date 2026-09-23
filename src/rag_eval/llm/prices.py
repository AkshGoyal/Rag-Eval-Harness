"""Where a model's price comes from.

Two sources, in order of authority. The gateway's live catalogue is the truth where
it has an answer. A small hand-maintained file fills the gaps the catalogue leaves,
and every entry in it records its source and the date it was checked.

What is never allowed is a third, implicit source: "unknown, so assume free". That
default once made every embedding call invisible to the spending limit.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_eval.errors import ConfigError
from rag_eval.llm.types import ModelPrice


class ManualPrice(BaseModel):
    """A price entered by hand, with its provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million: float = Field(ge=0.0)
    output_per_million: float = Field(default=0.0, ge=0.0)
    source: str = Field(min_length=1)
    checked: datetime.date

    def as_price(self) -> ModelPrice:
        """Drop the provenance and keep the numbers."""
        return ModelPrice(
            input_per_million=self.input_per_million,
            output_per_million=self.output_per_million,
        )


def load_manual_prices(path: Path) -> dict[str, ModelPrice]:
    """Read the hand-maintained price file. A missing file means no manual prices.

    Raises:
        ConfigError: if the file exists but is malformed, or an entry lacks its
            source or checked date.
    """
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"is not valid YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ConfigError(path, ["must be a mapping of model id to price"])

    prices: dict[str, ModelPrice] = {}
    problems: list[str] = []
    for model_id, entry in data.items():
        try:
            prices[str(model_id)] = ManualPrice.model_validate(entry).as_price()
        except ValidationError as exc:
            problems.extend(
                f"{model_id}.{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            )
    if problems:
        raise ConfigError(path, problems)
    return prices


def merge_prices(
    live: dict[str, ModelPrice], manual: dict[str, ModelPrice]
) -> dict[str, ModelPrice]:
    """Combine the two sources. The live catalogue wins wherever both have a price."""
    return {**manual, **live}

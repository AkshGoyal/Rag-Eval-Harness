"""What every retriever has to provide, regardless of how it searches."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from rag_eval.pipeline.chunking import Chunk


class Retrieved(BaseModel):
    """One chunk a retriever returned, with its score and its place in the ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    score: float
    chunk: Chunk


class Retriever(Protocol):
    """Find the chunks most likely to answer a question.

    Stated as a protocol so that comparing keyword search against vector search is a
    configuration change rather than a different code path through the harness.
    """

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        """Return the top ``top_k`` chunks for ``query``, best first."""
        ...

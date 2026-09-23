"""Vector search: find chunks whose meaning is closest to the question's.

Each chunk is turned into a list of numbers by an embedding model, once, and stored.
A question is turned into numbers the same way, and the chunks whose numbers point in
the most similar direction are returned. Unlike keyword search, this can match a
question to a passage that shares no words with it.

Search is exact — every chunk is compared against every question — for the reason
given in D-006: an approximate index can return different neighbours between builds,
which would make a score difference impossible to attribute to a configuration
change. At this corpus size exact search is one matrix multiplication.

Building an index is the only part of this project that costs real money at scale,
so the index is saved to disk under a key derived from everything that shaped it.
The same corpus, chunking and model always find the same saved index; changing any of
them builds a new one rather than silently reusing the old.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from rag_eval import __version__
from rag_eval.config import ChunkingConfig, EmbeddingConfig
from rag_eval.errors import RagEvalError
from rag_eval.hashing import JSONValue, sha256_of
from rag_eval.llm.client import ModelClient
from rag_eval.llm.types import EmbeddingRequest
from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.base import Retrieved

CHARACTERS_PER_TOKEN = 4.0
"""Rough English average, used only to estimate cost before spending anything."""


class DenseIndexError(RagEvalError):
    """A saved index is missing, corrupt, or does not match the chunks it claims to cover."""


def index_key(dataset_hash: str, chunking: ChunkingConfig, embedding: EmbeddingConfig) -> str:
    """Identify an index by everything that determines its contents.

    The batch size is left out: it changes how requests are grouped, not what vectors
    come back, so an index built in batches of 50 is the same index as one built in
    batches of 100.
    """
    payload: JSONValue = {
        "dataset": dataset_hash,
        "chunking": chunking.model_dump(mode="json"),
        "model": embedding.model,
        "provider": embedding.provider,
    }
    return sha256_of(payload)


def estimate_cost_usd(chunks: tuple[Chunk, ...], price_per_million: float) -> float:
    """Estimate what embedding these chunks will cost, before any call is made."""
    tokens = sum(len(chunk.text) for chunk in chunks) / CHARACTERS_PER_TOKEN
    return tokens * price_per_million / 1_000_000


@dataclass(frozen=True)
class BuildReport:
    """What building an index did, and what it cost."""

    reused: bool
    chunks: int
    dimensions: int
    requests: int
    cached_requests: int
    cost_usd: float
    providers_served: tuple[str, ...]


class DenseIndex:
    """Exact cosine-similarity search over stored chunk vectors."""

    def __init__(
        self,
        chunks: tuple[Chunk, ...],
        vectors: NDArray[np.float32],
        *,
        embed_query: Callable[[str], NDArray[np.float32]],
    ) -> None:
        """Wrap already-computed vectors. Rows are normalised so a dot product is cosine."""
        if len(chunks) != len(vectors):
            raise DenseIndexError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if not chunks:
            raise DenseIndexError("cannot search an index of zero chunks")
        self.chunks = chunks
        self.vectors = _normalise(vectors)
        self._embed_query = embed_query

    @property
    def dimensions(self) -> int:
        """How many numbers describe each chunk."""
        return int(self.vectors.shape[1])

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        """Return the ``top_k`` chunks closest in meaning to ``query``, best first.

        Ties break by chunk order, as in keyword search, so an identical query always
        produces an identical ranking.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be at least 1, got {top_k}")
        query_vector = _normalise(self._embed_query(query).reshape(1, -1))[0]
        if query_vector.shape[0] != self.dimensions:
            raise DenseIndexError(
                f"the question was embedded into {query_vector.shape[0]} dimensions "
                f"but the index holds {self.dimensions}; they came from different models"
            )
        scores = self.vectors @ query_vector
        wanted = min(top_k, len(self.chunks))
        order = np.lexsort((np.arange(len(scores)), -scores))[:wanted]
        return tuple(
            Retrieved(rank=rank, score=float(scores[position]), chunk=self.chunks[position])
            for rank, position in enumerate(order, start=1)
        )


def build_or_load(
    chunks: tuple[Chunk, ...],
    *,
    client: ModelClient,
    embedding: EmbeddingConfig,
    key: str,
    root: Path,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[DenseIndex, BuildReport]:
    """Load the saved index for ``key`` if there is one, otherwise build and save it.

    Every request goes through the model client, so each batch is cached as it
    completes. A build interrupted halfway — a lost connection, the spending limit —
    resumes where it stopped when run again, without paying twice for what was done.

    Raises:
        DenseIndexError: if a saved index does not cover exactly these chunks.
        ModelError, BudgetExceededError: from the client, if embedding fails.
    """
    directory = root / key[:16]

    def embed_query(text: str) -> NDArray[np.float32]:
        result = client.embed(
            EmbeddingRequest(model=embedding.model, inputs=(text,), provider=embedding.provider)
        )
        return np.asarray(result.vectors[0], dtype=np.float32)

    if (directory / "vectors.npy").is_file():
        vectors = _load(directory, chunks)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        return DenseIndex(chunks, vectors, embed_query=embed_query), BuildReport(
            reused=True,
            chunks=len(chunks),
            dimensions=int(vectors.shape[1]),
            requests=0,
            cached_requests=0,
            cost_usd=0.0,
            providers_served=tuple(manifest.get("providers_served", [])),
        )

    batches: list[NDArray[np.float32]] = []
    requests = cached = 0
    cost = 0.0
    providers: set[str] = set()
    size = embedding.batch_size
    total = (len(chunks) + size - 1) // size

    for number, start in enumerate(range(0, len(chunks), size), start=1):
        batch = chunks[start : start + size]
        result = client.embed(
            EmbeddingRequest(
                model=embedding.model,
                inputs=tuple(chunk.text for chunk in batch),
                provider=embedding.provider,
            )
        )
        batches.append(np.asarray(result.vectors, dtype=np.float32))
        requests += 1
        cached += int(result.record.cache_hit)
        cost += result.record.cost_usd
        if result.record.provider_served:
            providers.add(result.record.provider_served)
        if progress is not None:
            progress(number, total)

    vectors = np.vstack(batches)
    widths = {batch.shape[1] for batch in batches}
    if len(widths) != 1:
        raise DenseIndexError(
            f"batches came back with different vector sizes {sorted(widths)}; "
            "more than one model or provider served this build"
        )

    _save(directory, chunks, vectors, embedding, key, sorted(providers), cost)
    return DenseIndex(chunks, vectors, embed_query=embed_query), BuildReport(
        reused=False,
        chunks=len(chunks),
        dimensions=int(vectors.shape[1]),
        requests=requests,
        cached_requests=cached,
        cost_usd=cost,
        providers_served=tuple(sorted(providers)),
    )


def _normalise(vectors: NDArray[np.float32]) -> NDArray[np.float32]:
    """Scale each row to unit length, so that a dot product is cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise DenseIndexError("a vector of all zeros cannot be compared by direction")
    normalised: NDArray[np.float32] = np.divide(vectors, norms, dtype=np.float32)
    return normalised


def _save(
    directory: Path,
    chunks: tuple[Chunk, ...],
    vectors: NDArray[np.float32],
    embedding: EmbeddingConfig,
    key: str,
    providers: list[str],
    cost: float,
) -> None:
    """Write the vectors, the chunk order they correspond to, and how they were made."""
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "vectors.npy", vectors.astype(np.float32), allow_pickle=False)
    (directory / "chunk_ids.json").write_text(
        json.dumps([chunk.chunk_id for chunk in chunks]) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "key": key,
        "model": embedding.model,
        "provider_requested": embedding.provider,
        "providers_served": providers,
        "chunks": len(chunks),
        "dimensions": int(vectors.shape[1]),
        "cost_usd": round(cost, 8),
        "built_by": __version__,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _load(directory: Path, chunks: tuple[Chunk, ...]) -> NDArray[np.float32]:
    """Read saved vectors, refusing them unless they cover exactly these chunks in order."""
    try:
        stored_ids = json.loads((directory / "chunk_ids.json").read_text(encoding="utf-8"))
        vectors = np.asarray(
            np.load(directory / "vectors.npy", allow_pickle=False), dtype=np.float32
        )
    except (OSError, ValueError) as exc:
        raise DenseIndexError(f"the saved index in {directory} could not be read: {exc}") from exc
    expected = [chunk.chunk_id for chunk in chunks]
    if stored_ids != expected:
        raise DenseIndexError(
            f"the saved index in {directory} covers different chunks from the ones built "
            "now; delete that directory to rebuild it"
        )
    return vectors

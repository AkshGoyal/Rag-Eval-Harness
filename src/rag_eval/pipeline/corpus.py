"""Turning an ingested corpus into the chunks a retriever searches."""

from __future__ import annotations

from rag_eval.config import ChunkingConfig
from rag_eval.dataset.loader import Dataset
from rag_eval.pipeline.chunking import Chunk, chunk_text


def build_chunks(dataset: Dataset, chunking: ChunkingConfig) -> tuple[Chunk, ...]:
    """Chunk every contract in the corpus, in a stable order.

    Contracts are processed in identifier order so that the chunk list — and therefore
    the tie-breaking inside retrieval — is identical on every run.
    """
    chunks: list[Chunk] = []
    for entry in sorted(dataset.contracts, key=lambda item: item.contract_id):
        chunks.extend(
            chunk_text(
                dataset.text(entry.contract_id),
                entry.contract_id,
                size=chunking.size,
                overlap=chunking.overlap,
            )
        )
    return tuple(chunks)

"""Hybrid search: keyword and vector rankings merged into one.

The two methods fail differently. Keyword search is sharp when the question and the
contract share distinctive words, such as a date label or a defined term; vector
search finds a clause phrased differently from the question. Merging their rankings
aims to keep the strengths of both.

The merge is reciprocal rank fusion (RRF): each chunk scores ``1 / (rank_constant +
rank)`` in every ranking it appears in, and the scores are added. It uses ranks, not
raw scores, because a BM25 score and a cosine similarity are on unrelated scales, and
putting them on one scale would need a weight tuned on the test set — which, at
nineteen scored cases, would fit the noise.
"""

from __future__ import annotations

from collections.abc import Sequence

from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.base import Retrieved, Retriever


class HybridRetriever:
    """Merge several retrievers' rankings by reciprocal rank fusion."""

    def __init__(
        self,
        retrievers: Sequence[Retriever],
        chunks: tuple[Chunk, ...],
        *,
        rank_constant: int = 60,
        candidates: int = 100,
    ) -> None:
        """Set up the merge.

        Args:
            retrievers: the rankings to merge, each over the same ``chunks``.
            chunks: the corpus in its canonical order, used to break score ties.
            rank_constant: damps the advantage of the very top ranks. 60 is the value
                from the paper that introduced the method, and is used unchanged.
            candidates: how deep into each ranking to look. A chunk ranked below this
                by one method still counts if the other method ranks it.
        """
        if len(retrievers) < 2:
            raise ValueError("a hybrid needs at least two retrievers to merge")
        if rank_constant < 1 or candidates < 1:
            raise ValueError("rank_constant and candidates must both be at least 1")
        self._retrievers = tuple(retrievers)
        self._position = {chunk.chunk_id: position for position, chunk in enumerate(chunks)}
        self._chunks = chunks
        self._rank_constant = rank_constant
        self._candidates = candidates

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        """Return the ``top_k`` chunks with the highest fused score, best first.

        Ties break by chunk order, as in the methods being merged, so an identical
        query always produces an identical ranking.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be at least 1, got {top_k}")
        depth = max(top_k, self._candidates)
        fused: dict[int, float] = {}
        for retriever in self._retrievers:
            for hit in retriever.search(query, depth):
                position = self._position[hit.chunk.chunk_id]
                fused[position] = fused.get(position, 0.0) + 1.0 / (self._rank_constant + hit.rank)

        order = sorted(fused, key=lambda position: (-fused[position], position))[:top_k]
        return tuple(
            Retrieved(rank=rank, score=fused[position], chunk=self._chunks[position])
            for rank, position in enumerate(order, start=1)
        )

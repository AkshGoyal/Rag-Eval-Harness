"""Keyword search, scored with BM25.

BM25 ranks a passage by how often the query's words appear in it, discounting words
that are common across the whole corpus and correcting for passage length. It is the
lexical half of a hybrid retrieval stack, it needs no model and no credentials, and
it is completely deterministic — which makes it a sound baseline to compare vector
search against rather than merely a stopgap.

Scoring is exact: every chunk is scored on every query. At this corpus size that is a
few million multiply-adds in NumPy, and exactness is what lets a score difference be
attributed to a configuration change rather than to an index that varies.
"""

from __future__ import annotations

import re

import numpy as np

from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.base import Retrieved

_TOKEN = re.compile(r"[a-z0-9]+")

K1 = 1.5
"""Term-frequency saturation. Above this, repeating a word adds little."""

B = 0.75
"""How strongly to correct for passage length. 0 ignores length, 1 fully normalises."""


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. The same function is used for chunks and queries."""
    return _TOKEN.findall(text.lower())


class BM25Index:
    """An exact BM25 index over a fixed set of chunks.

    Stored as an inverted index — for each word, which chunks contain it and how often
    — rather than as a chunk-by-word matrix. The matrix would be mostly zeros and would
    need gigabytes at this corpus size; the inverted index needs tens of megabytes and
    lets a query touch only the chunks that contain its words.
    """

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        """Build the index. Chunk order is preserved and used to break score ties."""
        if not chunks:
            raise ValueError("cannot build an index over zero chunks")
        self.chunks = chunks

        raw: dict[str, dict[int, int]] = {}
        lengths = np.zeros(len(chunks), dtype=np.float32)

        for position, chunk in enumerate(chunks):
            tokens = tokenize(chunk.text)
            lengths[position] = len(tokens)
            for token in tokens:
                counts = raw.setdefault(token, {})
                counts[position] = counts.get(position, 0) + 1

        self.lengths = lengths
        self.average_length = float(lengths.mean()) if len(chunks) else 1.0
        if self.average_length <= 0.0:
            self.average_length = 1.0

        total = len(chunks)
        self._postings: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}
        for token, counts in raw.items():
            positions = np.fromiter(sorted(counts), dtype=np.int32, count=len(counts))
            frequencies = np.fromiter(
                (counts[int(p)] for p in positions), dtype=np.float32, count=len(counts)
            )
            document_frequency = len(counts)
            idf = float(
                np.log(1.0 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
            )
            self._postings[token] = (positions, frequencies, idf)

        # Length normalisation depends only on the chunk, so compute it once.
        self._norm = K1 * (1.0 - B + B * lengths / self.average_length)

    @property
    def vocabulary_size(self) -> int:
        """How many distinct words the corpus contains."""
        return len(self._postings)

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        """Return the best ``top_k`` chunks for ``query``, best first.

        Chunks scoring zero are omitted: a chunk sharing no words with the query was
        not retrieved, and padding the list to ``top_k`` with them would inflate
        recall while retrieving nothing useful.

        Ties are broken by chunk order, so the same query always produces the same
        ranking. Without that, two runs of an identical configuration could differ.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be at least 1, got {top_k}")

        scores = np.zeros(len(self.chunks), dtype=np.float32)
        matched = False
        for token in tokenize(query):
            posting = self._postings.get(token)
            if posting is None:
                continue
            matched = True
            positions, frequencies, idf = posting
            contribution = idf * frequencies * (K1 + 1.0) / (frequencies + self._norm[positions])
            np.add.at(scores, positions, contribution)
        if not matched:
            return ()

        wanted = min(top_k, len(self.chunks))
        order = np.lexsort((np.arange(len(scores)), -scores))[:wanted]

        return tuple(
            Retrieved(rank=rank, score=float(scores[position]), chunk=self.chunks[position])
            for rank, position in enumerate(order, start=1)
            if scores[position] > 0.0
        )

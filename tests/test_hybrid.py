from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.base import Retrieved
from rag_eval.retrieval.hybrid import HybridRetriever

CHUNKS = tuple(
    Chunk(
        chunk_id=f"c#{i:04d}", contract_id="c", index=i, start=i * 10, end=i * 10 + 5, text="text."
    )
    for i in range(6)
)


class Fixed:
    """A retriever that always returns the same ranking, given as chunk positions."""

    def __init__(self, positions: list[int]) -> None:
        self.positions = positions
        self.depths: list[int] = []

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        self.depths.append(top_k)
        return tuple(
            Retrieved(rank=rank, score=1.0 / rank, chunk=CHUNKS[position])
            for rank, position in enumerate(self.positions[:top_k], start=1)
        )


def _ids(results: tuple[Retrieved, ...]) -> list[str]:
    return [result.chunk.chunk_id for result in results]


def test_a_chunk_both_methods_rank_well_beats_one_only_one_ranks_first() -> None:
    """Agreement between the methods is the signal the merge exists to reward."""
    keyword = Fixed([0, 2, 3])
    vector = Fixed([1, 2, 4])

    results = HybridRetriever((keyword, vector), CHUNKS, rank_constant=60).search("q", 3)

    assert _ids(results)[0] == "c#0002"
    assert results[0].score == 2 / 62


def test_a_chunk_found_by_only_one_method_still_counts() -> None:
    results = HybridRetriever((Fixed([5]), Fixed([1])), CHUNKS).search("q", 5)

    assert set(_ids(results)) == {"c#0001", "c#0005"}


def test_ties_break_by_chunk_order_so_rankings_are_reproducible() -> None:
    """0 and 1 each appear once at rank 1: equal scores, so corpus order decides."""
    results = HybridRetriever((Fixed([1]), Fixed([0])), CHUNKS).search("q", 2)

    assert _ids(results) == ["c#0000", "c#0001"]
    assert [result.rank for result in results] == [1, 2]


def test_each_method_is_searched_to_the_candidate_depth() -> None:
    keyword, vector = Fixed([0]), Fixed([1])

    HybridRetriever((keyword, vector), CHUNKS, candidates=100).search("q", 5)

    assert keyword.depths == vector.depths == [100]

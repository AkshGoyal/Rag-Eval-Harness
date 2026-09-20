from itertools import pairwise

import pytest

from rag_eval.pipeline.chunking import Chunk, chunk_text
from rag_eval.retrieval.bm25 import BM25Index, tokenize

TEXT = (
    "This Distribution Agreement is made between Acme Corporation and Beta Industries. "
    "The Agreement shall be governed by the laws of the State of Delaware. "
    "Liability of either party is capped at one million dollars in the aggregate. "
    "Either party may terminate on thirty days written notice to the other party. "
)


# --- chunking ----------------------------------------------------------------


def test_short_text_becomes_one_chunk() -> None:
    chunks = chunk_text("A short contract.", "c1", size=500, overlap=50)

    assert len(chunks) == 1
    assert chunks[0].text == "A short contract."
    assert chunks[0].start == 0


def test_chunks_cover_the_document_in_order() -> None:
    chunks = chunk_text(TEXT, "c1", size=80, overlap=20)

    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].start == 0
    assert chunks[-1].end == len(TEXT)
    for earlier, later in pairwise(chunks):
        assert later.start < earlier.end, "consecutive chunks must overlap"


def test_offsets_always_describe_the_text() -> None:
    """Gold spans are compared against these offsets, so drift here corrupts scoring."""
    for chunk in chunk_text(TEXT, "c1", size=90, overlap=15):
        assert TEXT[chunk.start : chunk.end] == chunk.text


def test_words_are_not_split_across_chunks() -> None:
    for chunk in chunk_text(TEXT, "c1", size=70, overlap=10):
        stripped = chunk.text.strip()
        assert stripped
        assert stripped[0].isalnum() or not stripped[0].isspace()


def test_chunking_is_deterministic() -> None:
    first = chunk_text(TEXT, "c1", size=75, overlap=12)
    second = chunk_text(TEXT, "c1", size=75, overlap=12)

    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_overlap_at_or_above_size_is_refused() -> None:
    """Otherwise the cursor never advances and chunking never terminates."""
    with pytest.raises(ValueError, match="must be smaller"):
        chunk_text(TEXT, "c1", size=50, overlap=50)


def test_empty_text_yields_nothing() -> None:
    assert chunk_text("   \n  ", "c1", size=50, overlap=5) == ()


def test_chunk_ids_are_unique_and_ordered() -> None:
    chunks = chunk_text(TEXT, "c1", size=60, overlap=10)
    ids = [c.chunk_id for c in chunks]

    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)


@pytest.mark.parametrize(
    ("span", "expected"),
    [((0, 5), False), ((5, 15), True), ((95, 120), True), ((300, 400), False), ((99, 101), True)],
)
def test_chunk_knows_which_spans_it_covers(span: tuple[int, int], expected: bool) -> None:
    """Partial overlap counts: half a gold answer is still something worth finding."""
    chunk = Chunk(chunk_id="c#0", contract_id="c", index=0, start=10, end=100, text="x" * 90)

    assert chunk.covers(*span) is expected


# --- retrieval ---------------------------------------------------------------


def _chunks() -> tuple[Chunk, ...]:
    return chunk_text(TEXT, "acme", size=80, overlap=10)


def test_tokenizer_is_shared_by_queries_and_chunks() -> None:
    assert tokenize("Laws of DELAWARE, 1999!") == ["laws", "of", "delaware", "1999"]


def test_retrieval_finds_the_relevant_passage() -> None:
    index = BM25Index(_chunks())

    results = index.search("which law governs the agreement", top_k=3)

    assert results
    assert "Delaware" in results[0].chunk.text


def test_ranks_are_sequential_and_scores_descend() -> None:
    index = BM25Index(_chunks())

    results = index.search("party liability capped", top_k=4)

    assert [r.rank for r in results] == list(range(1, len(results) + 1))
    assert all(a.score >= b.score for a, b in pairwise(results))


def test_a_query_sharing_no_words_returns_nothing() -> None:
    """Padding to top_k with unrelated chunks would inflate recall while finding nothing."""
    index = BM25Index(_chunks())

    assert index.search("zebra xylophone quixotic", top_k=5) == ()


def test_retrieval_is_deterministic() -> None:
    """Two runs of one configuration must rank identically, or no delta means anything."""
    index = BM25Index(_chunks())

    first = index.search("terminate notice", top_k=5)
    second = index.search("terminate notice", top_k=5)

    assert [(r.rank, r.chunk.chunk_id) for r in first] == [
        (r.rank, r.chunk.chunk_id) for r in second
    ]


def test_ties_break_by_document_order() -> None:
    """Identical chunks must rank in a fixed order rather than an arbitrary one."""
    identical = tuple(
        Chunk(
            chunk_id=f"c#{i:04d}",
            contract_id="c",
            index=i,
            start=i * 10,
            end=i * 10 + 9,
            text="same text",
        )
        for i in range(5)
    )
    index = BM25Index(identical)

    results = index.search("same text", top_k=5)

    assert [r.chunk.index for r in results] == [0, 1, 2, 3, 4]


def test_top_k_is_respected() -> None:
    index = BM25Index(_chunks())

    assert len(index.search("agreement party", top_k=2)) <= 2


def test_an_empty_index_is_refused() -> None:
    with pytest.raises(ValueError, match="zero chunks"):
        BM25Index(())


def test_top_k_below_one_is_refused() -> None:
    index = BM25Index(_chunks())

    with pytest.raises(ValueError, match="at least 1"):
        index.search("anything", top_k=0)

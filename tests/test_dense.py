from pathlib import Path

import numpy as np
import pytest

from rag_eval.config import ChunkingConfig, ChunkStrategy, EmbeddingConfig
from rag_eval.llm.client import ModelClient
from rag_eval.llm.factory import build_client
from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.dense import (
    DenseIndex,
    DenseIndexError,
    build_or_load,
    estimate_cost_usd,
    index_key,
)

from .fakes import HashingGateway, as_base64, hashed_vector

TEXTS = (
    "This agreement is governed by the laws of the State of Delaware.",
    "Either party may terminate on thirty days written notice.",
    "Liability of either party is capped at one million dollars.",
    "The licensee shall maintain commercial general liability insurance.",
    "Payment is due within forty five days of invoice.",
)


def _chunks() -> tuple[Chunk, ...]:
    return tuple(
        Chunk(
            chunk_id=f"c#{i:04d}",
            contract_id="c",
            index=i,
            start=i * 100,
            end=i * 100 + len(t),
            text=t,
        )
        for i, t in enumerate(TEXTS)
    )


def _embedding(batch_size: int = 2) -> EmbeddingConfig:
    return EmbeddingConfig(model="fake/embedder", batch_size=batch_size)


def _client(tmp_path: Path, gateway: HashingGateway, limit_usd: float = 1.0) -> ModelClient:
    return build_client(
        gateway,
        cache_dir=tmp_path / "cache",
        limit_usd=limit_usd,
        api_key="test-key",
        base_url="https://example.test/api/v1",
        price_file=tmp_path / "no-prices.yaml",
    ).client


def test_vector_search_finds_the_passage_closest_in_meaning(tmp_path: Path) -> None:
    gateway = HashingGateway()
    index, report = build_or_load(
        _chunks(),
        client=_client(tmp_path, gateway),
        embedding=_embedding(),
        key="k" * 64,
        root=tmp_path / "indexes",
    )

    results = index.search("which state law governs this agreement", top_k=2)

    assert "Delaware" in results[0].chunk.text
    assert report.reused is False
    assert report.requests == 3, "five chunks in batches of two is three requests"


def test_a_saved_index_is_reused_without_calling_the_model(tmp_path: Path) -> None:
    """Building an index is the one real cost; the same inputs must never pay twice."""
    first_gateway = HashingGateway()
    build_or_load(
        _chunks(),
        client=_client(tmp_path, first_gateway),
        embedding=_embedding(),
        key="k" * 64,
        root=tmp_path / "indexes",
    )

    second_gateway = HashingGateway()
    _, report = build_or_load(
        _chunks(),
        client=_client(tmp_path / "other", second_gateway),
        embedding=_embedding(),
        key="k" * 64,
        root=tmp_path / "indexes",
    )

    assert report.reused is True
    assert second_gateway.embedding_requests == 0


def test_an_interrupted_build_resumes_from_the_cache(tmp_path: Path) -> None:
    """If a build dies halfway, completed batches must not be paid for again."""
    gateway = HashingGateway()
    client = _client(tmp_path, gateway)
    build_or_load(
        _chunks(), client=client, embedding=_embedding(), key="a" * 64, root=tmp_path / "indexes"
    )
    paid = gateway.embedding_requests

    _, report = build_or_load(
        _chunks(), client=client, embedding=_embedding(), key="b" * 64, root=tmp_path / "indexes"
    )

    assert gateway.embedding_requests == paid, "every batch should come from the cache"
    assert report.cached_requests == report.requests


def test_a_saved_index_for_different_chunks_is_refused(tmp_path: Path) -> None:
    gateway = HashingGateway()
    build_or_load(
        _chunks(),
        client=_client(tmp_path, gateway),
        embedding=_embedding(),
        key="k" * 64,
        root=tmp_path / "indexes",
    )

    with pytest.raises(DenseIndexError, match="different chunks"):
        build_or_load(
            _chunks()[:3],
            client=_client(tmp_path, gateway),
            embedding=_embedding(),
            key="k" * 64,
            root=tmp_path / "indexes",
        )


def test_the_index_key_changes_with_anything_that_changes_the_vectors() -> None:
    chunking = ChunkingConfig(strategy=ChunkStrategy.FIXED_CHAR, size=2000, overlap=250)
    base = index_key("d" * 64, chunking, EmbeddingConfig(model="a/model"))

    assert base != index_key("e" * 64, chunking, EmbeddingConfig(model="a/model"))
    assert base != index_key("d" * 64, chunking, EmbeddingConfig(model="b/model"))
    assert base != index_key(
        "d" * 64, chunking.model_copy(update={"size": 1000}), EmbeddingConfig(model="a/model")
    )
    assert base != index_key("d" * 64, chunking, EmbeddingConfig(model="a/model", provider="X"))


def test_batch_size_does_not_change_the_index_key() -> None:
    """Grouping requests differently returns the same vectors, so it is the same index."""
    chunking = ChunkingConfig(strategy=ChunkStrategy.FIXED_CHAR, size=2000, overlap=250)

    assert index_key("d" * 64, chunking, EmbeddingConfig(model="a/m", batch_size=10)) == index_key(
        "d" * 64, chunking, EmbeddingConfig(model="a/m", batch_size=200)
    )


def test_ranking_is_deterministic_and_ties_break_by_order() -> None:
    chunks = _chunks()
    vectors = np.ones((len(chunks), 4), dtype=np.float32)
    index = DenseIndex(chunks, vectors, embed_query=lambda _text: np.ones(4, dtype=np.float32))

    ranks = [r.chunk.index for r in index.search("anything", top_k=5)]

    assert ranks == [0, 1, 2, 3, 4]


def test_a_query_from_a_different_model_is_refused() -> None:
    chunks = _chunks()
    index = DenseIndex(
        chunks,
        np.ones((len(chunks), 4), dtype=np.float32),
        embed_query=lambda _text: np.ones(8, dtype=np.float32),
    )

    with pytest.raises(DenseIndexError, match="different models"):
        index.search("anything", top_k=1)


def test_the_cost_estimate_uses_about_four_characters_per_token() -> None:
    chunk = Chunk(
        chunk_id="c#0", contract_id="c", index=0, start=0, end=4_000_000, text="x" * 4_000_000
    )

    assert estimate_cost_usd((chunk,), price_per_million=0.02) == pytest.approx(0.02)


def test_base64_embeddings_decode_to_the_original_numbers() -> None:
    from rag_eval.llm.client import _vector_of

    vector = hashed_vector("governed by the laws of Delaware")

    assert list(_vector_of(as_base64(vector), 0)) == pytest.approx(vector)


def test_plain_list_embeddings_are_still_accepted() -> None:
    """A provider that ignores the request for base64 must not break the build."""
    from rag_eval.llm.client import _vector_of

    assert _vector_of([0.5, 0.25], 0) == (0.5, 0.25)


def test_corrupt_base64_is_refused() -> None:
    from rag_eval.llm.client import ModelError, _vector_of

    with pytest.raises(ModelError, match="base64"):
        _vector_of("not base64!!", 0)

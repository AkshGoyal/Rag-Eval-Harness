from pathlib import Path

import pytest

from rag_eval.config import RetrievalMethod, load_config
from rag_eval.errors import ConfigError

from .conftest import FIXTURES


def test_valid_config_loads_with_expected_values() -> None:
    config = load_config(FIXTURES / "valid.yaml")

    assert config.name == "fixture-valid"
    assert config.chunking.size == 512
    assert config.chunking.overlap == 64
    assert config.retrieval.top_k == 5
    assert config.retrieval.method is RetrievalMethod.DENSE
    assert config.embedding.model == "openai/text-embedding-3-small"
    assert config.embedding.provider is None
    assert config.generation.model == "meta-llama/llama-3.1-8b-instruct"
    assert config.corpus.hash is None


def test_config_is_immutable_after_loading() -> None:
    config = load_config(FIXTURES / "valid.yaml")

    with pytest.raises(Exception):  # noqa: B017 - pydantic's frozen error type is internal
        config.retrieval.top_k = 10


def test_unknown_field_is_rejected_and_named() -> None:
    """A mis-cased field must fail, not silently fall back to the default.

    This is the failure that would make an A/B run compare two identical
    configurations and report "no regression" with full confidence.
    """
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "unknown_field.yaml")

    problems = "\n".join(caught.value.problems)
    assert "retrieval.top_K" in problems
    assert "retrieval.top_k" in problems  # the real field is now missing, and is reported too


def test_wrong_type_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "wrong_type.yaml")

    assert any("retrieval.top_k" in problem for problem in caught.value.problems)


def test_overlap_at_or_above_chunk_size_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "overlap_too_large.yaml")

    problems = "\n".join(caught.value.problems)
    assert "chunking" in problems
    assert "never advances" in problems


def test_top_k_below_one_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "top_k_zero.yaml")

    assert any("retrieval.top_k" in problem for problem in caught.value.problems)


def test_unimplemented_retrieval_method_is_rejected() -> None:
    """Only implemented methods are accepted; `rerank` is not one of them."""
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "unimplemented_method.yaml")

    problems = "\n".join(caught.value.problems)
    assert "retrieval.method" in problems
    assert "dense" in problems  # the message tells the reader what is allowed


def test_missing_file_names_the_path() -> None:
    missing = FIXTURES / "does_not_exist.yaml"

    with pytest.raises(ConfigError) as caught:
        load_config(missing)

    assert caught.value.path == missing
    assert "cannot be read" in str(caught.value)


def test_empty_file_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "empty.yaml")

    assert caught.value.problems == ["is empty"]


def test_top_level_list_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "not_a_mapping.yaml")

    assert any("must be a mapping" in problem for problem in caught.value.problems)


def test_error_message_reports_every_problem_at_once() -> None:
    """One bad config should not require three runs to fix three mistakes."""
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "unknown_field.yaml")

    assert len(caught.value.problems) >= 2


@pytest.mark.parametrize(
    "alias",
    ["~deepseek/deepseek-v4-flash-latest", "deepseek/deepseek-flash-latest", "vendor/model:latest"],
)
def test_an_alias_model_id_is_rejected(tmp_path: Path, alias: str) -> None:
    """An alias can be re-pointed by the gateway, so identical configs could call two models."""
    text = (
        (FIXTURES / "valid.yaml")
        .read_text()
        .replace("model: deepseek/deepseek-v4-flash", f"model: {alias}")
    )
    path = tmp_path / "alias.yaml"
    path.write_text(text)

    with pytest.raises(ConfigError, match="alias"):
        load_config(path)


def test_a_model_id_without_a_vendor_is_rejected(tmp_path: Path) -> None:
    text = (
        (FIXTURES / "valid.yaml")
        .read_text()
        .replace("model: openai/text-embedding-3-small", "model: text-embedding-3-small")
    )
    path = tmp_path / "bare.yaml"
    path.write_text(text)

    with pytest.raises(ConfigError, match="vendor/model"):
        load_config(path)


@pytest.mark.parametrize(
    "name",
    ["baseline.yaml", "dense-openai-small.yaml", "dense-qwen-8b.yaml", "hybrid-openai-small.yaml"],
)
def test_the_shipped_configs_load(name: str) -> None:
    load_config(Path("configs") / name)


def test_the_dense_configs_differ_from_the_baseline_only_where_intended() -> None:
    """A comparison is only attributable if nothing else changed."""
    baseline = load_config(Path("configs/baseline.yaml")).model_dump()
    openai_small = load_config(Path("configs/dense-openai-small.yaml")).model_dump()
    qwen = load_config(Path("configs/dense-qwen-8b.yaml")).model_dump()

    def changed(a: dict[str, object], b: dict[str, object]) -> set[str]:
        return {key for key in a if a[key] != b[key]} - {"name"}

    assert changed(baseline, openai_small) == {"retrieval"}
    assert changed(openai_small, qwen) == {"embedding"}


def test_the_hybrid_config_differs_from_its_parts_only_in_retrieval() -> None:
    dense = load_config(Path("configs/dense-openai-small.yaml")).model_dump()
    hybrid = load_config(Path("configs/hybrid-openai-small.yaml")).model_dump()

    assert {key for key in dense if dense[key] != hybrid[key]} - {"name"} == {"retrieval"}
    assert hybrid["retrieval"]["method"] == "hybrid"


def test_hybrid_merge_settings_are_filled_in_and_fingerprinted(tmp_path: Path) -> None:
    """Implicit defaults would let a changed default alter results with no trace."""
    text = Path("configs/hybrid-openai-small.yaml").read_text(encoding="utf-8")
    bare = tmp_path / "bare.yaml"
    bare.write_text(text.replace("  hybrid:\n    rank_constant: 60\n    candidates: 100\n", ""))

    explicit = load_config(Path("configs/hybrid-openai-small.yaml"))
    implicit = load_config(bare)

    assert implicit.retrieval.hybrid is not None
    assert implicit.content_hash() == explicit.content_hash()


def test_hybrid_settings_on_another_method_are_rejected(tmp_path: Path) -> None:
    text = Path("configs/dense-openai-small.yaml").read_text(encoding="utf-8")
    path = tmp_path / "dense.yaml"
    path.write_text(text.replace("  top_k: 5\n", "  top_k: 5\n  hybrid:\n    candidates: 50\n"))

    with pytest.raises(ConfigError, match="only used when method is 'hybrid'"):
        load_config(path)

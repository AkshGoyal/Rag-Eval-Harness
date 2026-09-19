import pytest

from rag_eval.config import Provider, RetrievalMethod, load_config
from rag_eval.errors import ConfigError

from .conftest import FIXTURES


def test_valid_config_loads_with_expected_values() -> None:
    config = load_config(FIXTURES / "valid.yaml")

    assert config.name == "fixture-valid"
    assert config.chunking.size == 512
    assert config.chunking.overlap == 64
    assert config.retrieval.top_k == 5
    assert config.retrieval.method is RetrievalMethod.DENSE
    assert config.generation.provider is Provider.GOOGLE
    assert config.judge.provider is Provider.OPENAI
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
    """Only implemented methods are accepted; `hybrid` is planned, not available."""
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

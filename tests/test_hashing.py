import pytest

from rag_eval.config import load_config
from rag_eval.hashing import JSONValue, canonical_json, sha256_of

from .conftest import FIXTURES


def test_canonical_json_ignores_key_order() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_is_stable_across_calls() -> None:
    payload: JSONValue = {"z": [3, 2, 1], "a": {"nested": True}}

    assert canonical_json(payload) == canonical_json(payload)


def test_canonical_json_escapes_non_ascii() -> None:
    """Byte-stability must not depend on the filesystem or locale encoding."""
    assert canonical_json({"k": "café"}) == '{"k":"caf\\u00e9"}'


def test_unserialisable_value_is_refused_loudly() -> None:
    with pytest.raises(TypeError, match="cannot be hashed canonically"):
        sha256_of({"when": object()})  # type: ignore[dict-item]  # invalid on purpose


def test_config_hash_ignores_key_order_in_the_file() -> None:
    """The same configuration written in a different order is the same configuration."""
    original = load_config(FIXTURES / "valid.yaml")
    reordered = load_config(FIXTURES / "valid_reordered.yaml")

    assert original.content_hash() == reordered.content_hash()


def test_config_hash_ignores_name() -> None:
    """`name` is a label, not an input: renaming must not invalidate a cache entry."""
    config = load_config(FIXTURES / "valid.yaml")
    renamed = config.model_copy(update={"name": "a-different-label"})

    assert renamed.name != config.name
    assert renamed.content_hash() == config.content_hash()


def test_config_hash_changes_when_a_setting_changes() -> None:
    """Any field that can change the answers must change the hash."""
    config = load_config(FIXTURES / "valid.yaml")

    wider = config.model_copy(
        update={"retrieval": config.retrieval.model_copy(update={"top_k": 10})}
    )

    assert wider.content_hash() != config.content_hash()


def test_config_hash_changes_when_the_corpus_changes() -> None:
    """Different documents mean different answers, so the hash must differ."""
    config = load_config(FIXTURES / "valid.yaml")

    reingested = config.model_copy(
        update={"corpus": config.corpus.model_copy(update={"hash": "deadbeef"})}
    )

    assert reingested.content_hash() != config.content_hash()

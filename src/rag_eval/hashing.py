"""Canonical serialisation and content hashing.

Every number this harness reports must be traceable to the exact inputs that
produced it, and two identical inputs must produce the same identifier no matter
how they were written down. That rules out hashing raw file bytes: the same
configuration with its keys in a different order is the same configuration.

These helpers are used for configuration hashes now, dataset hashes at ingestion,
and - most importantly - response cache keys. A cache key that fails to change
when an input changes will serve a stale answer under a new name, and nothing
about the output will look wrong.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import TypeAlias

JSONValue: TypeAlias = "bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None"
"""Anything json can serialise without help.

Stated explicitly rather than as ``Any`` because these helpers underpin cache keys:
a value that slips through untyped is a value that can silently change a hash.
"""


def _encode_unsupported(obj: object) -> JSONValue:
    """Convert values json cannot serialise, or refuse loudly."""
    if isinstance(obj, StrEnum):
        return str(obj)
    raise TypeError(
        f"{type(obj).__name__} cannot be hashed canonically; "
        "convert it to a JSON-compatible value first"
    )


def canonical_json(obj: JSONValue) -> str:
    """Serialise ``obj`` to JSON with a byte-stable representation.

    Keys are sorted, separators are fixed, and non-ASCII is escaped, so the output
    depends on content alone - not on key order, whitespace, or locale.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_encode_unsupported,
    )


def sha256_of(obj: JSONValue) -> str:
    """Return the SHA-256 hex digest of ``obj``'s canonical JSON form."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()

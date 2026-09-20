"""A content-addressed cache for model responses.

The cache exists for two reasons. At this project's budget, re-running an evaluation
during development must not cost anything the second time. And a cached response
makes a rerun deterministic where the model itself is not.

Its correctness rests entirely on the key. A key that fails to change when an input
changes will serve an old answer under a new configuration's name, and nothing about
the output will look wrong — no error, no warning, just a number that is quietly
false. Every field capable of changing a model's output therefore goes into the key,
and the request models in ``types.py`` are defined so that this is automatic.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from rag_eval.errors import RagEvalError
from rag_eval.hashing import JSONValue, sha256_of


class CacheError(RagEvalError):
    """A cache entry could not be read or written."""


def cache_key(kind: str, request: BaseModel) -> str:
    """Fingerprint a request. Every field of the request takes part."""
    payload: JSONValue = {"kind": kind, "request": request.model_dump(mode="json")}
    return sha256_of(payload)


class ResponseCache:
    """Stores raw provider responses on disk, one file per request fingerprint."""

    def __init__(self, root: Path) -> None:
        """Create the cache. The directory is made on first write, not here."""
        self.root = root
        self.hits = 0
        self.misses = 0

    def path_for(self, key: str) -> Path:
        """Where an entry lives. Sharded by prefix to keep directories small."""
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> JSONValue | None:
        """Return a cached response, or None. A corrupt entry is an error, not a miss."""
        path = self.path_for(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            loaded: JSONValue = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Treating this as a miss would silently re-spend money and hide
            # a corrupted cache; both should be noticed.
            raise CacheError(f"cache entry {path} could not be read: {exc}") from exc
        self.hits += 1
        return loaded

    def put(self, key: str, response: JSONValue) -> None:
        """Store a response.

        Written to a temporary file and moved into place, so an interrupted write
        cannot leave a half-finished entry that would later read as corrupt.
        """
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(response, sort_keys=True), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            raise CacheError(f"cache entry {path} could not be written: {exc}") from exc

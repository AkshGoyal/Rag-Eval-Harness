"""A fake gateway for tests: priced catalogues, and embeddings that behave like embeddings.

The embedding is a hashed bag of words — each word adds weight to one of a fixed
number of dimensions. Texts that share words point in similar directions, so vector
search behaves meaningfully in tests without any network, key or cost.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from collections.abc import Mapping

from rag_eval.hashing import JSONValue

DIMENSIONS = 64
_WORD = re.compile(r"[a-z0-9]+")


def hashed_vector(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    """A deterministic stand-in for an embedding: shared words give similar vectors."""
    vector = [0.0] * dimensions
    for word in _WORD.findall(text.lower()):
        slot = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16)
        vector[slot % dimensions] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


def as_base64(vector: list[float]) -> str:
    """Encode a vector the way the real gateway does when asked for base64."""
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()


class HashingGateway:
    """Serves priced catalogues and hashed embeddings. Counts embedding requests."""

    def __init__(
        self,
        *,
        embed_model: str = "fake/embedder",
        price: str = "0.00000002",
        dimensions: int = DIMENSIONS,
    ) -> None:
        self.embed_model = embed_model
        self.price = price
        self.dimensions = dimensions
        self.embedding_requests = 0
        self.inputs_embedded = 0

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, JSONValue]:
        if url.endswith("/embeddings/models"):
            return 200, {"data": [{"id": self.embed_model, "pricing": {"prompt": self.price}}]}
        return 200, {"data": [{"id": "fake/chat", "pricing": {"prompt": "0.000001"}}]}

    def post(
        self, url: str, headers: Mapping[str, str], payload: JSONValue, timeout: float
    ) -> tuple[int, JSONValue]:
        assert isinstance(payload, dict)
        inputs = payload["input"]
        assert isinstance(inputs, list)
        self.embedding_requests += 1
        self.inputs_embedded += len(inputs)
        tokens = sum(len(str(text)) for text in inputs) // 4
        return 200, {
            "data": [
                {"index": i, "embedding": as_base64(hashed_vector(str(text), self.dimensions))}
                for i, text in enumerate(inputs)
            ],
            "usage": {"prompt_tokens": tokens},
            "provider": "FakeProvider",
        }


def dump(value: object) -> str:
    return json.dumps(value)

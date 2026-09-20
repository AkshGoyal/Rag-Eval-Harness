"""Splitting contracts into retrievable pieces.

Chunk size is measured in characters, not tokens. Tokenising would mean either a
runtime download of a vocabulary file or a heavy dependency, and this project's test
suite has to run with no network and no credentials. Characters are exact, need no
vocabulary, and behave identically on every machine.

The practical consequence is only that configuration values are in characters. As a
rough guide, English prose runs about four characters to a token, so a 2,000-character
chunk is in the region of 500 tokens — which is where the published chunking benchmarks
put their default.

Chunks never split a word. A boundary lands on whitespace, so a chunk always begins and
ends on something readable, and a retrieved passage shown to a person makes sense.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

_WHITESPACE = re.compile(r"\s")


class Chunk(BaseModel):
    """One retrievable piece of one contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    index: int = Field(ge=0, description="Position of this chunk within its contract.")
    start: int = Field(ge=0, description="Character offset into the contract text.")
    end: int = Field(ge=1, description="Exclusive end offset.")
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _offsets_must_describe_the_text(self) -> Chunk:
        """Keep offsets and text in step, since gold spans are compared against them."""
        if self.end <= self.start:
            raise ValueError(f"{self.chunk_id}: end ({self.end}) must exceed start ({self.start})")
        if self.end - self.start != len(self.text):
            raise ValueError(
                f"{self.chunk_id}: offsets span {self.end - self.start} characters "
                f"but the text carries {len(self.text)}"
            )
        return self

    def covers(self, start: int, end: int) -> bool:
        """Report whether this chunk overlaps a span of the contract at all.

        Any overlap counts. A gold answer split by a chunk boundary is still partly
        present in both chunks, and a retriever that returns either has found
        something genuinely useful — scoring that as a miss would understate it.
        """
        return self.start < end and start < self.end


def _boundary(text: str, position: int, *, forward: bool) -> int:
    """Move a cut to the nearest whitespace so no word is split in half."""
    if position <= 0 or position >= len(text):
        return max(0, min(position, len(text)))
    limit = 100
    step = 1 if forward else -1
    for offset in range(limit):
        probe = position + offset * step
        if 0 < probe < len(text) and _WHITESPACE.match(text[probe]):
            return probe
    return position


def chunk_text(text: str, contract_id: str, *, size: int, overlap: int) -> tuple[Chunk, ...]:
    """Split one contract into overlapping chunks.

    Args:
        text: the contract's full text.
        contract_id: used to build stable chunk identifiers.
        size: target chunk length in characters.
        overlap: characters shared between neighbouring chunks.

    Returns:
        Chunks in document order. A contract shorter than one chunk yields one chunk.

    Raises:
        ValueError: if overlap is not smaller than size, which would stop the cursor
            advancing and loop forever.
    """
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than size ({size})")

    stripped = text.strip()
    if not stripped:
        return ()

    chunks: list[Chunk] = []
    cursor = 0
    index = 0
    while cursor < len(text):
        stop = _boundary(text, min(cursor + size, len(text)), forward=True)
        if stop <= cursor:
            stop = min(cursor + size, len(text))
        piece = text[cursor:stop]
        if piece.strip():
            chunks.append(
                Chunk(
                    chunk_id=f"{contract_id}#{index:04d}",
                    contract_id=contract_id,
                    index=index,
                    start=cursor,
                    end=stop,
                    text=piece,
                )
            )
            index += 1
        if stop >= len(text):
            break
        cursor = _boundary(text, max(stop - overlap, cursor + 1), forward=True)
    return tuple(chunks)

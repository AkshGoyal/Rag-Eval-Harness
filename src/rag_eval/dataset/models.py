"""What a normalised dataset is, independent of where it came from.

Nothing here knows about CUAD. That knowledge lives in one place, ``cuad.py``, so
that pointing this harness at a different corpus - or at an external RAG system in
Phase 14 - does not require reshaping everything downstream.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_eval.hashing import JSONValue, sha256_of


class _Record(BaseModel):
    """Base for dataset records: immutable, and strict about unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Span(_Record):
    """A stretch of a document, given as character offsets into its text."""

    start: int = Field(ge=0)
    end: int = Field(ge=1, description="Exclusive; text[start:end] is the span.")
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _offsets_must_agree_with_text(self) -> Span:
        """Reject a span whose offsets do not describe the text it carries."""
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be greater than start ({self.start})")
        if self.end - self.start != len(self.text):
            raise ValueError(
                f"span covers {self.end - self.start} characters but carries "
                f"{len(self.text)}; the offsets and the text disagree"
            )
        return self


class ClauseLabel(_Record):
    """Whether one category of clause appears in one contract, and where.

    A label with ``present=False`` is data, not a gap: it is an expert's statement
    that the clause is absent, which makes it a case where the correct answer is a
    refusal rather than an invention.
    """

    contract_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    present: bool
    spans: tuple[Span, ...] = ()

    @model_validator(mode="after")
    def _presence_must_match_spans(self) -> ClauseLabel:
        """Reject the two states that would make a label self-contradictory."""
        if self.present and not self.spans:
            raise ValueError(f"{self.contract_id}/{self.category}: marked present with no spans")
        if not self.present and self.spans:
            raise ValueError(
                f"{self.contract_id}/{self.category}: marked absent but carries "
                f"{len(self.spans)} span(s)"
            )
        return self


class ContractIndexEntry(_Record):
    """One row of the contract index: enough to verify a file without reading it all."""

    contract_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    characters: int = Field(ge=1)


class Category(_Record):
    """One clause category, as the corpus authors describe it."""

    name: str = Field(min_length=1)
    description: str = ""
    answer_format: str = ""
    group: str = ""


class DatasetManifest(_Record):
    """What an ingestion produced, and from what.

    ``created_at`` is recorded but deliberately excluded from ``content_hash``.
    Including it would give the same data a different fingerprint on every
    ingestion, which would make the fingerprint useless for the one job it has.
    """

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_member: str = Field(min_length=1)
    member_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_count: int = Field(ge=1)
    label_count: int = Field(ge=1)
    present_label_count: int = Field(ge=0)
    category_count: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingested_by: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


def content_hash(
    contracts: tuple[ContractIndexEntry, ...],
    labels: tuple[ClauseLabel, ...],
    categories: tuple[Category, ...],
) -> str:
    """Fingerprint a dataset from its content alone.

    Everything is sorted first, so the fingerprint does not depend on the order
    records happened to be produced in. Contract texts enter through their own
    hashes, recorded in the index, rather than being re-read here.
    """
    payload: JSONValue = {
        "contracts": [c.model_dump(mode="json") for c in sorted(contracts, key=_contract_key)],
        "labels": [label.model_dump(mode="json") for label in sorted(labels, key=_label_key)],
        "categories": [c.model_dump(mode="json") for c in sorted(categories, key=lambda c: c.name)],
    }
    return sha256_of(payload)


def _contract_key(entry: ContractIndexEntry) -> str:
    return entry.contract_id


def _label_key(label: ClauseLabel) -> tuple[str, str]:
    return (label.contract_id, label.category)

"""What a test case is.

A case pairs one question with one contract and states what a correct answer looks
like. Everything a case asserts comes from CUAD's expert annotations - the answer
text, where it sits in the document, and whether the clause is there at all - so no
reference answer in this project was written by a model or guessed at.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_eval.dataset.models import Span


class CaseType(StrEnum):
    """What a case asks the system to do.

    The five types fall out of the corpus rather than being imposed on it. CUAD asks
    two shapes of question - "what is the value" and "is this kind of clause here at
    all" - and each can be answerable or not.
    """

    EXTRACTION_SINGLE = "extraction_single"
    """Pull one value out of one place in the contract."""

    EXTRACTION_MULTI = "extraction_multi"
    """Pull a value that is spread across several places. The multi-hop case."""

    EXISTENCE_YES = "existence_yes"
    """Confirm a kind of clause is present, with evidence."""

    EXISTENCE_NO = "existence_no"
    """State that a kind of clause is absent. The hallucination trap: the tempting
    failure is to find something roughly similar and call it a match."""

    NOT_STATED = "not_stated"
    """Decline to give a value the contract does not contain."""


class TestCase(BaseModel):
    """One question, one contract, and what a correct answer would be."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    __test__: ClassVar[bool] = False
    """Not a pytest test class, despite the name."""

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    contract_name: str = Field(min_length=1, description="Readable name used in the question.")
    category: str = Field(min_length=1)
    case_type: CaseType
    requires_refusal: bool = Field(
        description="True when the correct answer is that the contract does not say."
    )
    reference_answer: str = Field(min_length=1)
    gold_spans: tuple[Span, ...] = Field(
        description="Where a correct answer is found. Empty when the clause is absent."
    )
    phrasing_index: int = Field(ge=0, description="Which phrasing of the template was used.")
    answer_overlap: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Share of the reference answer's distinctive words that already appear in "
            "the question. High values mean the question gives away its own answer."
        ),
    )

    @model_validator(mode="after")
    def _spans_must_match_refusal(self) -> TestCase:
        """Reject a case that both requires a refusal and points at evidence."""
        if self.requires_refusal and self.gold_spans:
            raise ValueError(f"{self.case_id}: requires refusal but carries gold spans")
        if not self.requires_refusal and not self.gold_spans:
            raise ValueError(f"{self.case_id}: answerable but carries no gold spans")
        return self


class TestSetManifest(BaseModel):
    """What a build produced, and from what, so it can be reproduced exactly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    templates_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    counts_by_type: dict[str, int]
    excluded_for_leakage: int = Field(ge=0)
    max_answer_overlap: float = Field(ge=0.0, le=1.0)
    overlap_threshold: float = Field(ge=0.0, le=1.0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    built_by: str = Field(min_length=1)
    created_at: str = Field(min_length=1)

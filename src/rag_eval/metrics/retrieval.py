"""Scoring retrieval on its own, before any answer is written.

This is the half of the evaluation that needs no judge and no model output: for each
question, did the passages retrieved contain the answer? It is exactly checkable,
because every answerable case records where in which contract its answer lives.

Three measures, because "recall" is used loosely and they answer different questions:

* **hit@k** — did any of the top k passages contain any part of the answer?
* **span recall@k** — what share of the answer's separate pieces did the top k cover?
  Identical to hit@k for a single-piece answer; for a multi-hop question, whose answer
  is split across several places, it is the stricter and more honest measure.
* **MRR** — the mean of 1/rank of the first passage containing the answer. Rewards
  putting it first rather than merely somewhere in the top k.

Cases whose correct answer is a refusal have no passage to find, so they cannot be
scored here. They are counted and reported, never silently dropped: a score over
nineteen cases must not read as a score over thirty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from rag_eval.dataset.models import Span
from rag_eval.llm.budget import BudgetExceededError
from rag_eval.retrieval.base import Retrieved
from rag_eval.testset.models import TestCase

DEFAULT_KS: tuple[int, ...] = (1, 3, 5, 10)


class Searcher(Protocol):
    """Anything that ranks chunks for a question."""

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        """Return up to ``top_k`` chunks, best first."""
        ...


@dataclass(frozen=True)
class CaseResult:
    """How retrieval did on one case."""

    case_id: str
    case_type: str
    question: str
    first_hit_rank: int | None
    spans_total: int
    spans_found_by_rank: tuple[int | None, ...]
    """For each gold span, the rank of the first retrieved chunk covering it."""
    error: str | None = None

    def hit_at(self, k: int) -> bool:
        """Whether any part of the answer was in the top ``k``."""
        return self.first_hit_rank is not None and self.first_hit_rank <= k

    def span_recall_at(self, k: int) -> float:
        """Share of the answer's pieces covered within the top ``k``."""
        found = sum(1 for rank in self.spans_found_by_rank if rank is not None and rank <= k)
        return found / self.spans_total if self.spans_total else 0.0

    @property
    def reciprocal_rank(self) -> float:
        """One over the rank of the first passage containing the answer, or zero."""
        return 1.0 / self.first_hit_rank if self.first_hit_rank else 0.0


@dataclass(frozen=True)
class GroupScore:
    """Averages over a group of scored cases."""

    cases: int
    hit_at: dict[int, float]
    span_recall_at: dict[int, float]
    mrr: float


@dataclass(frozen=True)
class RetrievalReport:
    """Retrieval scores for a whole test set, with everything not scored accounted for."""

    results: tuple[CaseResult, ...]
    not_scored: int
    """Refusal cases: their correct answer is that nothing should be found."""
    ks: tuple[int, ...] = DEFAULT_KS
    by_type: dict[str, GroupScore] = field(default_factory=dict)
    overall: GroupScore | None = None

    @property
    def errors(self) -> tuple[CaseResult, ...]:
        """Cases where retrieval itself failed. Reported beside the scores, never hidden."""
        return tuple(result for result in self.results if result.error is not None)


def score_case(case: TestCase, retrieved: Sequence[Retrieved]) -> CaseResult:
    """Score one answerable case against a ranked list of retrieved chunks.

    A chunk counts only if it comes from the right contract and overlaps a gold span.
    A passage about the same clause type in a different contract is a miss.
    """
    spans_found: list[int | None] = []
    for span in case.gold_spans:
        spans_found.append(_first_rank_covering(case.contract_id, span, retrieved))
    ranks = [rank for rank in spans_found if rank is not None]
    return CaseResult(
        case_id=case.case_id,
        case_type=case.case_type.value,
        question=case.question,
        first_hit_rank=min(ranks) if ranks else None,
        spans_total=len(case.gold_spans),
        spans_found_by_rank=tuple(spans_found),
    )


def _first_rank_covering(
    contract_id: str, span: Span, retrieved: Sequence[Retrieved]
) -> int | None:
    for item in retrieved:
        if item.chunk.contract_id == contract_id and item.chunk.covers(span.start, span.end):
            return item.rank
    return None


def evaluate_retrieval(
    cases: Sequence[TestCase],
    searcher: Searcher,
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> RetrievalReport:
    """Run every answerable case through ``searcher`` and score it.

    One failing case does not stop the run. It is recorded as an error with its reason
    and counted against the group it belongs to, so a score never quietly means "the
    score among the cases that did not fail". The exception is the spending limit,
    which stops the run outright.
    """
    depth = max(ks)
    results: list[CaseResult] = []
    not_scored = 0
    for case in cases:
        if case.requires_refusal:
            not_scored += 1
            continue
        try:
            retrieved = searcher.search(case.question, depth)
        except BudgetExceededError:
            # Reaching the spending limit ends the run. Recording it per case would turn
            # "stopped at the limit" into "every remaining case errored", which is false.
            raise
        except Exception as exc:
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    case_type=case.case_type.value,
                    question=case.question,
                    first_hit_rank=None,
                    spans_total=len(case.gold_spans),
                    spans_found_by_rank=tuple(None for _ in case.gold_spans),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        results.append(score_case(case, retrieved))

    by_type: dict[str, list[CaseResult]] = {}
    for result in results:
        by_type.setdefault(result.case_type, []).append(result)

    return RetrievalReport(
        results=tuple(results),
        not_scored=not_scored,
        ks=ks,
        by_type={name: _aggregate(group, ks) for name, group in sorted(by_type.items())},
        overall=_aggregate(results, ks) if results else None,
    )


def _aggregate(results: Sequence[CaseResult], ks: tuple[int, ...]) -> GroupScore:
    """Average over a group. An errored case scores zero, so errors cannot inflate a score."""
    count = len(results)
    return GroupScore(
        cases=count,
        hit_at={k: sum(r.hit_at(k) for r in results) / count for k in ks},
        span_recall_at={k: sum(r.span_recall_at(k) for r in results) / count for k in ks},
        mrr=sum(r.reciprocal_rank for r in results) / count,
    )

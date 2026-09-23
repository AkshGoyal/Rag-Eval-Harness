import pytest

from rag_eval.dataset.models import Span
from rag_eval.llm.budget import BudgetExceededError
from rag_eval.metrics.retrieval import evaluate_retrieval, score_case
from rag_eval.pipeline.chunking import Chunk
from rag_eval.retrieval.base import Retrieved
from rag_eval.testset.models import CaseType, TestCase


def _case(
    case_id: str = "c1",
    *,
    spans: tuple[tuple[int, int], ...] = ((100, 120),),
    contract: str = "acme",
    case_type: CaseType = CaseType.EXTRACTION_SINGLE,
) -> TestCase:
    refusal = not spans
    return TestCase(
        case_id=case_id,
        question="Which law governs the Acme agreement?",
        contract_id=contract,
        contract_name="the Acme agreement",
        category="Governing Law",
        case_type=CaseType.EXISTENCE_NO if refusal else case_type,
        requires_refusal=refusal,
        reference_answer="No." if refusal else "Delaware",
        gold_spans=tuple(Span(start=s, end=e, text="x" * (e - s)) for s, e in spans),
        phrasing_index=0,
        answer_overlap=0.0,
    )


def _hit(rank: int, contract: str, start: int, end: int) -> Retrieved:
    chunk = Chunk(
        chunk_id=f"{contract}#{rank:04d}",
        contract_id=contract,
        index=rank,
        start=start,
        end=end,
        text="y" * (end - start),
    )
    return Retrieved(rank=rank, score=1.0 / rank, chunk=chunk)


def test_a_chunk_covering_the_answer_is_a_hit_at_its_rank() -> None:
    result = score_case(_case(), [_hit(1, "acme", 0, 50), _hit(2, "acme", 90, 130)])

    assert result.first_hit_rank == 2
    assert not result.hit_at(1)
    assert result.hit_at(2)
    assert result.reciprocal_rank == pytest.approx(0.5)


def test_the_right_passage_in_the_wrong_contract_is_a_miss() -> None:
    """Retrieval searches 510 contracts; the same clause type elsewhere is not the answer."""
    result = score_case(_case(), [_hit(1, "other", 90, 130)])

    assert result.first_hit_rank is None
    assert result.reciprocal_rank == 0.0


def test_span_recall_counts_each_piece_of_a_split_answer() -> None:
    """A multi-hop answer with one of two pieces found is half recalled, not a full hit."""
    case = _case(spans=((100, 120), (900, 920)), case_type=CaseType.EXTRACTION_MULTI)

    result = score_case(case, [_hit(1, "acme", 90, 130), _hit(2, "acme", 2000, 2100)])

    assert result.hit_at(1)
    assert result.span_recall_at(5) == pytest.approx(0.5)


class _Fixed:
    def __init__(self, results: tuple[Retrieved, ...]) -> None:
        self.results = results

    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        return self.results[:top_k]


def test_refusal_cases_are_counted_not_scored() -> None:
    """A score over 19 cases must not read as a score over 30."""
    report = evaluate_retrieval(
        [_case("a"), _case("b", spans=())], _Fixed((_hit(1, "acme", 90, 130),))
    )

    assert len(report.results) == 1
    assert report.not_scored == 1


class _Failing:
    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        raise RuntimeError("embedding service unavailable")


def test_a_failing_case_is_recorded_and_scores_zero() -> None:
    """Errors sit beside scores, and cannot inflate them by dropping out of the average."""
    report = evaluate_retrieval([_case("a"), _case("b")], _Failing())

    assert len(report.errors) == 2
    assert report.overall is not None
    assert report.overall.hit_at[10] == 0.0
    assert report.overall.cases == 2


class _OverBudget:
    def search(self, query: str, top_k: int) -> tuple[Retrieved, ...]:
        raise BudgetExceededError(0.5, 0.5, 10)


def test_reaching_the_spending_limit_stops_the_run() -> None:
    """Recording it per case would turn "stopped at the limit" into "everything errored"."""
    with pytest.raises(BudgetExceededError):
        evaluate_retrieval([_case("a"), _case("b")], _OverBudget())


def test_scores_are_grouped_by_case_type() -> None:
    cases = [_case("a"), _case("b", case_type=CaseType.EXISTENCE_YES)]

    report = evaluate_retrieval(cases, _Fixed((_hit(1, "acme", 90, 130),)))

    assert set(report.by_type) == {"extraction_single", "existence_yes"}
    assert report.overall is not None and report.overall.cases == 2

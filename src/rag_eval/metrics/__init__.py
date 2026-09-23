"""Deterministic scoring. No model is involved in anything here."""

from rag_eval.metrics.retrieval import (
    CaseResult,
    GroupScore,
    RetrievalReport,
    evaluate_retrieval,
    score_case,
)

__all__ = ["CaseResult", "GroupScore", "RetrievalReport", "evaluate_retrieval", "score_case"]

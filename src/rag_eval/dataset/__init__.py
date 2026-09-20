"""Turning a published corpus into a versioned, verifiable local dataset."""

from rag_eval.dataset.loader import load_dataset
from rag_eval.dataset.models import (
    Category,
    ClauseLabel,
    ContractIndexEntry,
    DatasetManifest,
    Span,
    content_hash,
)

__all__ = [
    "Category",
    "ClauseLabel",
    "ContractIndexEntry",
    "DatasetManifest",
    "Span",
    "content_hash",
    "load_dataset",
]

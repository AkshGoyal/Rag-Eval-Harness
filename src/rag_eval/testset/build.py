"""Selecting test cases from the corpus, reproducibly.

Given the same dataset, the same phrasings and the same seed, this produces exactly
the same cases in exactly the same order. That matters because a test set that
drifts makes every comparison against an earlier run meaningless.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rag_eval import __version__
from rag_eval.dataset.models import ClauseLabel, ContractIndexEntry
from rag_eval.errors import DatasetError
from rag_eval.hashing import JSONValue, sha256_of
from rag_eval.testset.leakage import answer_overlap
from rag_eval.testset.models import CaseType, TestCase, TestSetManifest
from rag_eval.testset.naming import unique_display_names
from rag_eval.testset.templates import Style, TemplateSet


class ManifestView(Protocol):
    """The parts of a dataset manifest a test set needs to record.

    Declared read-only so that an immutable dataset satisfies it.
    """

    @property
    def name(self) -> str:
        """The corpus name."""

    @property
    def version(self) -> str:
        """The corpus version."""

    @property
    def content_hash(self) -> str:
        """The corpus fingerprint."""


class CorpusView(Protocol):
    """What building a test set requires of a corpus.

    Stated as a protocol rather than the concrete loaded dataset so that the builder
    does not depend on how the corpus reached it. That is the same seam an external
    system will arrive through in Phase 14.
    """

    @property
    def labels(self) -> tuple[ClauseLabel, ...]:
        """Every clause label in the corpus."""

    @property
    def contracts(self) -> tuple[ContractIndexEntry, ...]:
        """The contract index."""

    @property
    def manifest(self) -> ManifestView:
        """What the corpus records about itself."""


OVERLAP_THRESHOLD = 0.5
"""Reject a case when half or more of its answer's distinctive words are already in
the question. Chosen to catch questions that hand over the answer while tolerating
incidental word sharing; every rejection is counted in the manifest rather than
dropped quietly."""

MAX_CASES_PER_CONTRACT = 2
"""Keep the set spread across contracts, so scores are not dominated by whether one
document happens to chunk well."""

SEED_STRATA: dict[CaseType, int] = {
    CaseType.EXTRACTION_SINGLE: 7,
    CaseType.EXTRACTION_MULTI: 6,
    CaseType.EXISTENCE_YES: 6,
    CaseType.EXISTENCE_NO: 8,
    CaseType.NOT_STATED: 3,
}
"""The seed set: thirty cases, weighted for variety rather than to mirror the corpus,
which is two-thirds absences."""


def classify(label: ClauseLabel, style: Style) -> CaseType:
    """Decide what a case asks of the system."""
    if style is Style.EXTRACTION:
        if not label.present:
            return CaseType.NOT_STATED
        return CaseType.EXTRACTION_MULTI if len(label.spans) >= 2 else CaseType.EXTRACTION_SINGLE
    return CaseType.EXISTENCE_YES if label.present else CaseType.EXISTENCE_NO


def reference_answer(label: ClauseLabel, case_type: CaseType) -> str:
    """State what a correct answer contains, using only expert-annotated text."""
    if case_type is CaseType.NOT_STATED:
        return "The contract does not state this."
    if case_type is CaseType.EXISTENCE_NO:
        return "No."
    if case_type is CaseType.EXISTENCE_YES:
        return "Yes."
    return " ... ".join(span.text.strip() for span in label.spans)


def _rank(seed: str, key: str) -> str:
    """Derive a stable ordering key: same inputs, same order, always."""
    return hashlib.sha256(f"{seed}|{key}".encode()).hexdigest()


def build_testset(
    dataset: CorpusView,
    templates: TemplateSet,
    *,
    name: str = "seed-v1",
    seed: str = "rag-eval-harness/seed-v1",
    strata: dict[CaseType, int] | None = None,
) -> tuple[tuple[TestCase, ...], TestSetManifest]:
    """Select a stratified, reproducible sample of cases.

    Raises:
        DatasetError: if a clause category has no phrasings, or if a stratum cannot
            be filled. A short stratum is reported rather than silently accepted,
            because a category with too few cases cannot support a claim about it.
    """
    wanted = dict(strata or SEED_STRATA)
    by_category = templates.by_category()

    missing = sorted({label.category for label in dataset.labels} - set(by_category))
    if missing:
        raise DatasetError("templates", [f"no phrasing for category {name!r}" for name in missing])

    names = unique_display_names({entry.contract_id: entry.title for entry in dataset.contracts})

    candidates: dict[CaseType, list[tuple[str, ClauseLabel]]] = {
        case_type: [] for case_type in CaseType
    }
    for label in dataset.labels:
        case_type = classify(label, by_category[label.category].style)
        candidates[case_type].append((_rank(seed, f"{label.contract_id}|{label.category}"), label))
    for pool in candidates.values():
        pool.sort(key=lambda item: item[0])

    cases: list[TestCase] = []
    per_contract: Counter[str] = Counter()
    excluded = 0
    shortfalls: list[str] = []

    for case_type, quota in wanted.items():
        taken = 0
        for rank, label in candidates[case_type]:
            if taken >= quota:
                break
            if per_contract[label.contract_id] >= MAX_CASES_PER_CONTRACT:
                continue

            template = by_category[label.category]
            index = int(rank[:8], 16) % len(template.phrasings)
            contract_name = names[label.contract_id]
            question = template.phrasings[index].format(contract=contract_name)
            answer = reference_answer(label, case_type)
            overlap = answer_overlap(question, answer)

            if overlap >= OVERLAP_THRESHOLD:
                excluded += 1
                continue

            cases.append(
                TestCase(
                    case_id=f"{name}-{len(cases) + 1:04d}",
                    question=question,
                    contract_id=label.contract_id,
                    contract_name=contract_name,
                    category=label.category,
                    case_type=case_type,
                    requires_refusal=case_type in (CaseType.EXISTENCE_NO, CaseType.NOT_STATED),
                    reference_answer=answer,
                    gold_spans=label.spans,
                    phrasing_index=index,
                    answer_overlap=round(overlap, 4),
                )
            )
            per_contract[label.contract_id] += 1
            taken += 1

        if taken < quota:
            shortfalls.append(f"{case_type.value}: wanted {quota}, found {taken}")

    if shortfalls:
        raise DatasetError("test set", shortfalls)

    counts = Counter(case.case_type.value for case in cases)
    manifest = TestSetManifest(
        name=name,
        dataset_name=dataset.manifest.name,
        dataset_version=dataset.manifest.version,
        dataset_content_hash=dataset.manifest.content_hash,
        templates_hash=templates.content_hash(),
        seed=seed,
        case_count=len(cases),
        counts_by_type=dict(sorted(counts.items())),
        excluded_for_leakage=excluded,
        max_answer_overlap=max((case.answer_overlap for case in cases), default=0.0),
        overlap_threshold=OVERLAP_THRESHOLD,
        content_hash=_cases_hash(tuple(cases)),
        built_by=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    return tuple(cases), manifest


def _cases_hash(cases: tuple[TestCase, ...]) -> str:
    """Fingerprint the cases themselves, independent of when they were built."""
    payload: JSONValue = [case.model_dump(mode="json") for case in cases]
    return sha256_of(payload)


def write_testset(out_dir: Path, cases: tuple[TestCase, ...], manifest: TestSetManifest) -> None:
    """Write the cases and their manifest side by side."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{manifest.name}.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")
    (out_dir / f"{manifest.name}.manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )

from pathlib import Path

import pytest

from rag_eval.dataset.models import ClauseLabel, ContractIndexEntry, Span
from rag_eval.errors import ConfigError, DatasetError
from rag_eval.testset.build import (
    MAX_CASES_PER_CONTRACT,
    NAMING_CATEGORIES,
    OVERLAP_THRESHOLD,
    ManifestView,
    build_testset,
    classify,
    reference_answer,
)
from rag_eval.testset.leakage import answer_overlap, distinctive_words
from rag_eval.testset.models import CaseType
from rag_eval.testset.naming import display_name, unique_display_names
from rag_eval.testset.templates import Style, load_templates

TEMPLATES = Path("testset/templates.yaml")


# --- naming ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "GALERATHERAPEUTICS,INC_02_14_2020-EX-99.A-JOINT FILING AGREEMENT",
            "the Galeratherapeutics, Inc Joint Filing Agreement",
        ),
        (
            "PcquoteComInc_19990721_S-1A_EX-10.11_6377149_EX-10.11_Co-Branding Agreement1",
            "the Pcquotecominc Co-Branding Agreement (No. 1)",
        ),
        (
            "Monsanto Company - SECOND A_R EXCLUSIVE AGENCY AND MARKETING AGREEMENT ",
            "the Monsanto Company - Second A R Exclusive Agency And Marketing Agreement",
        ),
    ],
)
def test_display_names_are_readable(title: str, expected: str) -> None:
    assert display_name(title) == expected


def test_exhibit_marker_does_not_eat_the_document_type() -> None:
    """The marker pattern once ran on past "EX-10.11_" and ate "Co-" from "Co-Branding"."""
    name = display_name("X_2019_EX-10.11_999_EX-10.11_Co-Branding Agreement")
    assert "Co-Branding" in name


def test_colliding_names_are_made_distinct() -> None:
    names = unique_display_names(
        {
            "a": "ACME_01_01_2020-EX-1-SUPPLY AGREEMENT",
            "b": "ACME_01_01_2021-EX-1-SUPPLY AGREEMENT",
            "c": "ACME_01_01_2021-EX-2-SUPPLY AGREEMENT",
        }
    )

    assert len(set(names.values())) == 3


# --- leakage -----------------------------------------------------------------


def test_common_words_are_not_distinctive() -> None:
    assert distinctive_words("Does the contract include a cap?") == frozenset({"include"})


def test_yes_and_no_answers_cannot_leak() -> None:
    """An existence answer carries no distinctive words, so overlap is zero by construction."""
    assert answer_overlap("Does the Acme Supply Agreement cap liability?", "Yes.") == 0.0


def test_a_question_containing_its_answer_scores_high() -> None:
    overlap = answer_overlap(
        "What is the Delaware Holdings Supply Agreement formally titled?",
        "Delaware Holdings Supply Agreement",
    )
    assert overlap >= OVERLAP_THRESHOLD


# --- classification ----------------------------------------------------------


def _label(present: bool, spans: int) -> ClauseLabel:
    return ClauseLabel(
        contract_id="c",
        category="Governing Law",
        present=present,
        spans=tuple(Span(start=i * 10, end=i * 10 + 4, text="abcd") for i in range(spans)),
    )


@pytest.mark.parametrize(
    ("style", "present", "spans", "expected"),
    [
        (Style.EXTRACTION, True, 1, CaseType.EXTRACTION_SINGLE),
        (Style.EXTRACTION, True, 3, CaseType.EXTRACTION_MULTI),
        (Style.EXTRACTION, False, 0, CaseType.NOT_STATED),
        (Style.EXISTENCE, True, 2, CaseType.EXISTENCE_YES),
        (Style.EXISTENCE, False, 0, CaseType.EXISTENCE_NO),
    ],
)
def test_case_types_follow_the_data(
    style: Style, present: bool, spans: int, expected: CaseType
) -> None:
    assert classify(_label(present, spans), style) is expected


def test_reference_answers_come_from_the_annotations_only() -> None:
    label = ClauseLabel(
        contract_id="c",
        category="Governing Law",
        present=True,
        spans=(Span(start=0, end=8, text="Delaware"),),
    )

    assert reference_answer(label, CaseType.EXTRACTION_SINGLE) == "Delaware"
    assert reference_answer(_label(False, 0), CaseType.EXISTENCE_NO) == "No."
    assert "does not state" in reference_answer(_label(False, 0), CaseType.NOT_STATED)


# --- templates ---------------------------------------------------------------


def test_the_shipped_templates_load_and_cover_every_category() -> None:
    templates = load_templates(TEMPLATES)

    assert len(templates.templates) == 41
    assert all(template.phrasings for template in templates.templates)


def test_a_phrasing_without_the_placeholder_is_rejected(tmp_path: Path) -> None:
    """A question that never names its contract cannot be answered from 510 of them."""
    bad = tmp_path / "t.yaml"
    bad.write_text(
        "version: 1\ntemplates:\n  - category: X\n    style: existence\n"
        "    phrasings: ['Is there a cap?']\n"
    )

    with pytest.raises(ConfigError, match="placeholder"):
        load_templates(bad)


def test_missing_template_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_templates(tmp_path / "nope.yaml")


# --- building ----------------------------------------------------------------


class _FakeManifest:
    """The manifest fields a test set build records."""

    name: str = "fake"
    version: str = "v1"
    content_hash: str = "1" * 64


class _FakeDataset:
    """A corpus small enough to reason about, shaped like the real one."""

    def __init__(self, labels: tuple[ClauseLabel, ...]) -> None:
        ids = sorted({label.contract_id for label in labels})
        self.labels = labels
        self.contracts = tuple(
            ContractIndexEntry(
                contract_id=cid,
                title=f"{cid.upper()}_01_01_2020-EX-1-SUPPLY AGREEMENT",
                sha256="0" * 64,
                characters=100,
            )
            for cid in ids
        )
        self.manifest: ManifestView = _FakeManifest()


def _pool(n: int, category: str, present: bool, spans: int) -> tuple[ClauseLabel, ...]:
    return tuple(
        ClauseLabel(
            contract_id=f"c{i:03d}",
            category=category,
            present=present,
            spans=tuple(Span(start=j * 20, end=j * 20 + 9, text="clause xy") for j in range(spans)),
        )
        for i in range(n)
    )


def _dataset() -> _FakeDataset:
    return _FakeDataset(
        _pool(40, "Governing Law", True, 1)
        + _pool(40, "Insurance", True, 2)
        + _pool(40, "Non-Compete", False, 0)
    )


def test_building_is_reproducible() -> None:
    """Same dataset, same phrasings, same seed, same cases — or comparisons are meaningless."""
    templates = load_templates(TEMPLATES)
    strata = {CaseType.EXTRACTION_SINGLE: 4, CaseType.EXISTENCE_YES: 4, CaseType.EXISTENCE_NO: 4}

    first, first_manifest = build_testset(_dataset(), templates, strata=strata)
    second, second_manifest = build_testset(_dataset(), templates, strata=strata)

    assert [case.model_dump() for case in first] == [case.model_dump() for case in second]
    assert first_manifest.content_hash == second_manifest.content_hash


def test_a_different_seed_selects_different_cases() -> None:
    templates = load_templates(TEMPLATES)
    strata = {CaseType.EXTRACTION_SINGLE: 4, CaseType.EXISTENCE_YES: 4, CaseType.EXISTENCE_NO: 4}

    a, _ = build_testset(_dataset(), templates, strata=strata, seed="one")
    b, _ = build_testset(_dataset(), templates, strata=strata, seed="two")

    assert {case.contract_id for case in a} != {case.contract_id for case in b}


def test_strata_are_respected() -> None:
    templates = load_templates(TEMPLATES)
    strata = {CaseType.EXTRACTION_SINGLE: 3, CaseType.EXISTENCE_NO: 5}

    cases, manifest = build_testset(_dataset(), templates, strata=strata)

    assert manifest.counts_by_type == {"existence_no": 5, "extraction_single": 3}
    assert len(cases) == 8


def test_no_contract_dominates_the_set() -> None:
    templates = load_templates(TEMPLATES)
    cases, _ = build_testset(
        _dataset(),
        templates,
        strata={CaseType.EXTRACTION_SINGLE: 10, CaseType.EXISTENCE_YES: 10},
    )

    counts: dict[str, int] = {}
    for case in cases:
        counts[case.contract_id] = counts.get(case.contract_id, 0) + 1
    assert max(counts.values()) <= MAX_CASES_PER_CONTRACT


def test_a_stratum_that_cannot_be_filled_is_reported() -> None:
    """Too few cases in a category cannot support a claim about that category."""
    templates = load_templates(TEMPLATES)

    with pytest.raises(DatasetError, match="wanted 999"):
        build_testset(_dataset(), templates, strata={CaseType.EXTRACTION_SINGLE: 999})


def test_a_category_with_no_phrasing_is_rejected() -> None:
    templates = load_templates(TEMPLATES)
    dataset = _FakeDataset(_pool(5, "Invented Category", True, 1))

    with pytest.raises(DatasetError, match="no phrasing"):
        build_testset(dataset, templates, strata={CaseType.EXTRACTION_SINGLE: 1})


def test_refusal_cases_carry_no_evidence() -> None:
    templates = load_templates(TEMPLATES)
    cases, _ = build_testset(_dataset(), templates, strata={CaseType.EXISTENCE_NO: 5})

    assert all(case.requires_refusal and case.gold_spans == () for case in cases)


@pytest.mark.parametrize("name", ["seed-v1", "seed-v2"])
def test_shipped_seed_sets_are_intact(name: str) -> None:
    """Both committed sets stay loadable: seed-v1 results are on record against it."""
    import json

    committed = [
        json.loads(line) for line in Path(f"testset/{name}.jsonl").read_text().splitlines()
    ]
    manifest = json.loads(Path(f"testset/{name}.manifest.json").read_text())

    assert len(committed) == manifest["case_count"] == 30
    assert all(case["answer_overlap"] < OVERLAP_THRESHOLD for case in committed)
    assert manifest["max_answer_overlap"] < OVERLAP_THRESHOLD


def test_the_current_seed_set_never_asks_what_names_the_contract() -> None:
    import json

    lines = Path("testset/seed-v2.jsonl").read_text().splitlines()
    manifest = json.loads(Path("testset/seed-v2.manifest.json").read_text())

    assert not {json.loads(line)["category"] for line in lines} & set(NAMING_CATEGORIES)
    assert tuple(manifest["excluded_categories"]) == NAMING_CATEGORIES


def test_naming_categories_are_never_selected() -> None:
    """The contract is named from these annotations, so asking about them leaks."""
    parties = tuple(
        label.model_copy(
            update={
                "spans": (
                    Span(start=0, end=9, text="Acme Corp"),
                    Span(start=20, end=29, text="Beta Corp"),
                )
            }
        )
        for label in _pool(40, "Parties", True, 2)
    )
    dataset = _FakeDataset(parties + _pool(40, "Governing Law", True, 2))
    templates = load_templates(TEMPLATES)

    cases, manifest = build_testset(dataset, templates, strata={CaseType.EXTRACTION_MULTI: 10})

    assert len(cases) == 10
    assert {case.category for case in cases} == {"Governing Law"}
    assert manifest.excluded_categories == NAMING_CATEGORIES


def test_rebuilding_an_unchanged_set_leaves_its_files_untouched(tmp_path: Path) -> None:
    """A rewrite that only changed a timestamp would block the next git pull."""
    from rag_eval.testset.build import write_testset

    templates = load_templates(TEMPLATES)
    strata = {CaseType.EXTRACTION_SINGLE: 3}
    cases, manifest = build_testset(_dataset(), templates, strata=strata)
    write_testset(tmp_path, cases, manifest)
    before = (tmp_path / "seed-v2.manifest.json").read_bytes()

    again, later = build_testset(_dataset(), templates, strata=strata)
    write_testset(
        tmp_path, again, later.model_copy(update={"created_at": "2099-01-01T00:00:00+00:00"})
    )

    assert (tmp_path / "seed-v2.manifest.json").read_bytes() == before

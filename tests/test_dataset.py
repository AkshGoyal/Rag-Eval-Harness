import io
import json
import zipfile
from pathlib import Path

import pytest

from rag_eval.dataset.cuad import (
    parse_categories,
    parse_contracts,
    reconcile_category_names,
    slugify,
)
from rag_eval.dataset.ingest import ingest_cuad
from rag_eval.dataset.loader import load_dataset
from rag_eval.dataset.models import DatasetManifest
from rag_eval.errors import DatasetError

from .conftest import FIXTURES

MINI = FIXTURES / "cuad_mini.json"
CATEGORIES = FIXTURES / "cuad_categories_mini.csv"


def _archive(json_path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("CUADv1.json", json_path.read_bytes())
    return buffer.getvalue()


def _ingest(tmp_path: Path, json_path: Path = MINI, csv_path: Path = CATEGORIES) -> DatasetManifest:
    return ingest_cuad(
        tmp_path,
        archive=_archive(json_path),
        categories_csv=csv_path.read_bytes(),
        verify_source=False,
    )


# --- parsing -----------------------------------------------------------------


def test_slug_is_filesystem_safe_and_stable() -> None:
    assert slugify("ALPHA_CORP-EX-10-DISTRIBUTION AGREEMENT") == (
        "alpha-corp-ex-10-distribution-agreement"
    )


def test_parses_contracts_and_labels() -> None:
    contracts, labels = parse_contracts(MINI.read_bytes())

    assert len(contracts) == 2
    assert len(labels) == 8
    assert sum(1 for label in labels if label.present) == 5


def test_absent_clauses_are_recorded_as_data_not_dropped() -> None:
    """A clause an expert confirmed is missing is a refusal case, not a gap."""
    _, labels = parse_contracts(MINI.read_bytes())
    absent = [label for label in labels if not label.present]

    assert {label.category for label in absent} == {"Source Code Escrow", "Cap On Liability"}
    assert all(label.spans == () for label in absent)


def test_multi_span_answers_are_kept_whole() -> None:
    """An answer scattered through a contract is a multi-hop retrieval case."""
    _, labels = parse_contracts(MINI.read_bytes())
    cap = next(label for label in labels if label.category == "Cap On Liability" and label.present)

    assert len(cap.spans) == 2


def test_every_span_points_at_the_text_it_carries() -> None:
    contracts, labels = parse_contracts(MINI.read_bytes())
    texts = {contract_id: text for contract_id, _, text in contracts}

    for label in labels:
        for span in label.spans:
            assert texts[label.contract_id][span.start : span.end] == span.text


def test_a_wrong_offset_is_rejected_and_named() -> None:
    """The most important check in the parser: drifted offsets corrupt every score."""
    with pytest.raises(DatasetError) as caught:
        parse_contracts((FIXTURES / "cuad_mini_bad_offset.json").read_bytes())

    problems = "\n".join(caught.value.problems)
    assert "Governing Law" in problems
    assert "points at" in problems


def test_colliding_contract_identifiers_are_rejected() -> None:
    with pytest.raises(DatasetError) as caught:
        parse_contracts((FIXTURES / "cuad_mini_duplicate_ids.json").read_bytes())

    assert any("share this identifier" in problem for problem in caught.value.problems)


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(DatasetError, match="not valid JSON"):
        parse_contracts(b"{not json")


def test_category_descriptions_are_cleaned_of_prefixes_and_bom() -> None:
    categories = parse_categories(CATEGORIES.read_bytes())
    by_name = {category.name: category for category in categories}

    assert "Document Name" in by_name
    assert by_name["Document Name"].description == "The name of the contract"
    assert by_name["Governing Law"].answer_format == "State"


def test_a_category_used_but_not_described_is_rejected() -> None:
    """Phase 3 turns these descriptions into questions; a missing one degrades silently."""
    _, labels = parse_contracts(MINI.read_bytes())
    categories = parse_categories((FIXTURES / "cuad_categories_incomplete.csv").read_bytes())

    with pytest.raises(DatasetError) as caught:
        reconcile_category_names(labels, categories)

    assert any("Governing Law" in problem for problem in caught.value.problems)


def test_category_names_take_the_human_spelling_from_the_csv() -> None:
    """CUAD title-cases its identifiers; the CSV has the spelling a person wrote."""
    _, labels = parse_contracts(MINI.read_bytes())
    categories = parse_categories(
        b"\xef\xbb\xbfCategory (incl. context and answer),Description,Answer Format,Group\n"
        b"Document Name,The name,Contract Name,-\n"
        b"Governing Law,Which law,State,1\n"
        b"Cap on Liability,The ceiling,Amount,2\n"
        b"Source Code Escrow,Escrowed,Yes/No,3\n"
    )

    aligned = reconcile_category_names(labels, categories)

    names = {label.category for label in aligned}
    assert "Cap on Liability" in names
    assert "Cap On Liability" not in names


# --- ingestion and loading ---------------------------------------------------


def test_ingestion_writes_the_expected_layout(tmp_path: Path) -> None:
    manifest = _ingest(tmp_path)

    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "labels.jsonl").is_file()
    assert (tmp_path / "contracts.jsonl").is_file()
    assert (tmp_path / "categories.json").is_file()
    assert len(list((tmp_path / "contracts").glob("*.txt"))) == 2
    assert manifest.contract_count == 2
    assert manifest.label_count == 8
    assert manifest.present_label_count == 5


def test_ingesting_twice_gives_the_same_fingerprint_but_a_new_timestamp(
    tmp_path: Path,
) -> None:
    """The timestamp must stay out of the fingerprint, or the fingerprint is useless."""
    first = _ingest(tmp_path / "a")
    second = _ingest(tmp_path / "b")

    assert first.content_hash == second.content_hash
    assert first.created_at is not None and second.created_at is not None


def test_changing_a_contract_changes_the_fingerprint(tmp_path: Path) -> None:
    baseline = _ingest(tmp_path / "a")

    altered = json.loads(MINI.read_text())
    altered["data"][1]["paragraphs"][0]["context"] += "\nAn added clause.\n"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(altered))

    changed = _ingest(tmp_path / "b", json_path=edited)

    assert changed.content_hash != baseline.content_hash


def test_loader_round_trips_an_ingested_dataset(tmp_path: Path) -> None:
    manifest = _ingest(tmp_path)
    dataset = load_dataset(tmp_path)

    assert dataset.manifest.content_hash == manifest.content_hash
    assert len(dataset.contracts) == 2
    assert "DISTRIBUTION AGREEMENT" in dataset.text(dataset.contracts[0].contract_id)


def test_loader_detects_a_contract_edited_after_ingestion(tmp_path: Path) -> None:
    """Documents shifting under a comparison is the failure hardest to diagnose."""
    _ingest(tmp_path)
    victim = next((tmp_path / "contracts").glob("*.txt"))
    victim.write_text(victim.read_text() + "\nquietly appended\n", encoding="utf-8")

    with pytest.raises(DatasetError) as caught:
        load_dataset(tmp_path)

    assert any("has changed since ingestion" in problem for problem in caught.value.problems)


def test_loader_detects_a_deleted_contract(tmp_path: Path) -> None:
    _ingest(tmp_path)
    next((tmp_path / "contracts").glob("*.txt")).unlink()

    with pytest.raises(DatasetError, match="missing"):
        load_dataset(tmp_path)


def test_loader_reports_a_missing_manifest_helpfully(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="has ingestion been run"):
        load_dataset(tmp_path)


def test_unknown_contract_is_named(tmp_path: Path) -> None:
    _ingest(tmp_path)
    dataset = load_dataset(tmp_path)

    with pytest.raises(DatasetError, match="no contract named"):
        dataset.text("not-a-real-contract")


def test_source_fingerprint_mismatch_stops_ingestion(tmp_path: Path) -> None:
    """Verification on means a changed upstream file halts rather than silently loads."""
    with pytest.raises(DatasetError) as caught:
        ingest_cuad(
            tmp_path,
            archive=_archive(MINI),
            categories_csv=CATEGORIES.read_bytes(),
            verify_source=True,
        )

    assert any("recorded fingerprint" in problem for problem in caught.value.problems)

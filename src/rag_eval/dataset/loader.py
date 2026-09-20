"""Read a dataset back from disk, and prove it has not changed since ingestion.

This is the guard against the most confusing failure available to us: documents
shifting underneath a comparison, so that scores move and a configuration change
takes the blame for it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from rag_eval.dataset.models import (
    Category,
    ClauseLabel,
    ContractIndexEntry,
    DatasetManifest,
    content_hash,
)
from rag_eval.errors import DatasetError
from rag_eval.hashing import JSONValue


@dataclass(frozen=True)
class Dataset:
    """An ingested corpus, verified against its manifest."""

    root: Path
    manifest: DatasetManifest
    contracts: tuple[ContractIndexEntry, ...]
    labels: tuple[ClauseLabel, ...]
    categories: tuple[Category, ...]

    def text(self, contract_id: str) -> str:
        """Return one contract's full text.

        Raises:
            DatasetError: if the contract is not part of this dataset.
        """
        path = self.root / "contracts" / f"{contract_id}.txt"
        if not path.is_file():
            raise DatasetError(str(self.root), [f"no contract named {contract_id!r}"])
        return path.read_text(encoding="utf-8")


def load_dataset(root: Path, *, verify_files: bool = True) -> Dataset:
    """Load a dataset and verify it against its own manifest.

    Args:
        root: the directory an ingestion wrote.
        verify_files: also re-hash every contract file. Catches edits to the text
            itself, which the index would otherwise not notice. Costs a few seconds
            on the full corpus.

    Raises:
        DatasetError: if a file is missing or unreadable, a contract's text no longer
            matches its recorded hash, or the recomputed fingerprint differs from the
            manifest. Every mismatching contract is named.
    """
    manifest = _read_manifest(root)
    contracts = tuple(
        ContractIndexEntry.model_validate(row) for row in _read_lines(root / "contracts.jsonl")
    )
    labels = tuple(ClauseLabel.model_validate(row) for row in _read_lines(root / "labels.jsonl"))
    categories = tuple(
        Category.model_validate(row) for row in _read_json_list(root / "categories.json")
    )

    problems: list[str] = []
    if verify_files:
        problems.extend(_file_mismatches(root, contracts))

    recomputed = content_hash(contracts, labels, categories)
    if recomputed != manifest.content_hash:
        problems.append(
            "the dataset's fingerprint no longer matches its manifest "
            f"(manifest {manifest.content_hash[:12]}, recomputed {recomputed[:12]})"
        )
    if problems:
        raise DatasetError(str(root), problems)

    return Dataset(
        root=root,
        manifest=manifest,
        contracts=contracts,
        labels=labels,
        categories=categories,
    )


def _file_mismatches(root: Path, contracts: tuple[ContractIndexEntry, ...]) -> list[str]:
    """Name every contract whose file is missing or no longer matches its hash."""
    problems: list[str] = []
    for entry in contracts:
        path = root / "contracts" / f"{entry.contract_id}.txt"
        if not path.is_file():
            problems.append(f"{entry.contract_id}: contract file is missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry.sha256:
            problems.append(f"{entry.contract_id}: contract text has changed since ingestion")
    return problems


def _read_manifest(root: Path) -> DatasetManifest:
    path = root / "manifest.json"
    if not path.is_file():
        raise DatasetError(str(root), ["manifest.json is missing; has ingestion been run?"])
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise DatasetError(str(path), ["must contain a JSON object"])
    return DatasetManifest.model_validate(payload)


def _read_json_list(path: Path) -> list[JSONValue]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise DatasetError(str(path), ["must contain a JSON list"])
    return payload


def _read_json(path: Path) -> JSONValue:
    if not path.is_file():
        raise DatasetError(str(path), ["is missing"])
    try:
        loaded: JSONValue = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except json.JSONDecodeError as exc:
        raise DatasetError(str(path), [f"is not valid JSON: {exc}"]) from exc


def _read_lines(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise DatasetError(str(path), ["is missing"])
    rows: list[dict[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise DatasetError(str(path), [f"line {number} is not valid JSON: {exc}"]) from exc
    return rows


__all__ = ["Dataset", "load_dataset"]

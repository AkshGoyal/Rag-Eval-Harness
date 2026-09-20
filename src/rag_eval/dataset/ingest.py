"""Fetch the published corpus, verify it, and write a normalised dataset to disk.

The verification is the point. Every score this harness produces depends on the
documents it searched, so a corpus that quietly changes between runs would move the
numbers and leave a configuration change to take the blame. The archive is checked
against a recorded fingerprint before anything is unpacked, and the dataset written
out carries a fingerprint of its own.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from rag_eval import __version__
from rag_eval.dataset.cuad import parse_categories, parse_contracts, reconcile_category_names
from rag_eval.dataset.models import (
    Category,
    ClauseLabel,
    ContractIndexEntry,
    DatasetManifest,
    content_hash,
)
from rag_eval.errors import DatasetError

CUAD_SOURCE_URL = "https://raw.githubusercontent.com/The-Atticus-Project/cuad/main/data.zip"
"""Where the archive is fetched from. Chosen because it is a plain HTTPS download,
reachable without git, from both a developer machine and a restricted environment."""

CUAD_ARCHIVE_SHA256 = "f8161d18bea4e9c05e78fa6dda61c19c846fb8087ea969c172753bc2f45b999a"
CUAD_MEMBER = "CUADv1.json"
CUAD_MEMBER_SHA256 = "ed0b77d85bdf4014d7495800e8e4a70565b48ee6f8a2e5dca9cf8655dbf10eae"
CUAD_CATEGORIES_URL = (
    "https://raw.githubusercontent.com/The-Atticus-Project/cuad/main/category_descriptions.csv"
)

_DOWNLOAD_TIMEOUT_SECONDS = 300


def fetch(url: str) -> bytes:
    """Download a URL, or fail with the URL named.

    Raises:
        DatasetError: on any network or HTTP failure. There is no retry here on
            purpose: ingestion is a deliberate, occasional act, and a silent retry
            would hide an unreachable source behind a longer wait.
    """
    try:
        with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
            payload: bytes = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise DatasetError(url, [f"could not be downloaded: {exc}"]) from exc
    if not payload:
        raise DatasetError(url, ["downloaded zero bytes"])
    return payload


def sha256_bytes(payload: bytes) -> str:
    """Hex digest of a byte string."""
    return hashlib.sha256(payload).hexdigest()


def _require_digest(what: str, payload: bytes, expected: str) -> None:
    """Stop if a downloaded file is not the file we recorded."""
    actual = sha256_bytes(payload)
    if actual != expected:
        raise DatasetError(
            what,
            [
                "content does not match the recorded fingerprint, so this is not the "
                "data this dataset version was built from",
                f"expected {expected}",
                f"found    {actual}",
            ],
        )


def ingest_cuad(
    out_dir: Path,
    *,
    archive: bytes | None = None,
    categories_csv: bytes | None = None,
    verify_source: bool = True,
) -> DatasetManifest:
    """Build a normalised CUAD dataset at ``out_dir`` and return its manifest.

    Args:
        out_dir: directory to write into. Created if absent; existing dataset files
            are replaced.
        archive: the zip archive's bytes. Downloaded when omitted.
        categories_csv: the category description CSV's bytes. Downloaded when omitted.
        verify_source: check the downloaded bytes against the recorded fingerprints.
            Only the tests turn this off, and only because their fixtures are
            deliberately small rather than the real corpus.

    Raises:
        DatasetError: if the source cannot be fetched, does not match its recorded
            fingerprint, or contains records that fail validation.
    """
    if archive is None:
        archive = fetch(CUAD_SOURCE_URL)
    if categories_csv is None:
        categories_csv = fetch(CUAD_CATEGORIES_URL)
    if verify_source:
        _require_digest(CUAD_SOURCE_URL, archive, CUAD_ARCHIVE_SHA256)

    member = _read_member(archive, CUAD_MEMBER)
    if verify_source:
        _require_digest(CUAD_MEMBER, member, CUAD_MEMBER_SHA256)

    contracts, labels = parse_contracts(member)
    categories = parse_categories(categories_csv)
    labels = reconcile_category_names(labels, categories)

    index = tuple(
        ContractIndexEntry(
            contract_id=contract_id,
            title=title,
            sha256=sha256_bytes(text.encode("utf-8")),
            characters=len(text),
        )
        for contract_id, title, text in contracts
    )

    manifest = DatasetManifest(
        name="cuad",
        version="v1",
        source_url=CUAD_SOURCE_URL,
        source_sha256=sha256_bytes(archive),
        source_member=CUAD_MEMBER,
        member_sha256=sha256_bytes(member),
        contract_count=len(index),
        label_count=len(labels),
        present_label_count=sum(1 for label in labels if label.present),
        category_count=len(categories),
        content_hash=content_hash(index, labels, categories),
        ingested_by=__version__,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    _write(out_dir, contracts, index, labels, categories, manifest)
    return manifest


def _read_member(archive: bytes, name: str) -> bytes:
    """Pull one named file out of a zip archive."""
    try:
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            return bundle.read(name)
    except KeyError as exc:
        raise DatasetError(name, ["is not present in the archive"]) from exc
    except zipfile.BadZipFile as exc:
        raise DatasetError("archive", [f"is not a readable zip file: {exc}"]) from exc


def _write(
    out_dir: Path,
    contracts: tuple[tuple[str, str, str], ...],
    index: tuple[ContractIndexEntry, ...],
    labels: tuple[ClauseLabel, ...],
    categories: tuple[Category, ...],
    manifest: DatasetManifest,
) -> None:
    """Lay the dataset out on disk, sorted so the result is reproducible."""
    contracts_dir = out_dir / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    for contract_id, _, text in contracts:
        (contracts_dir / f"{contract_id}.txt").write_text(text, encoding="utf-8")

    _write_lines(
        out_dir / "contracts.jsonl",
        [entry.model_dump(mode="json") for entry in sorted(index, key=lambda e: e.contract_id)],
    )
    _write_lines(
        out_dir / "labels.jsonl",
        [
            label.model_dump(mode="json")
            for label in sorted(labels, key=lambda label: (label.contract_id, label.category))
        ],
    )
    (out_dir / "categories.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in sorted(categories, key=lambda c: c.name)],
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_lines(path: Path, rows: list[dict[str, object]]) -> None:
    """Write one compact JSON object per line."""
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")

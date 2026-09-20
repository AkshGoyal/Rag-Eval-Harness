"""The only file that knows what CUAD's published format looks like.

CUAD ships as a SQuAD-style JSON file: one entry per contract, carrying the full
contract text and 41 questions asked of it, each either answered with character
offsets into that text or marked as having no answer. A separate CSV describes the
41 clause categories.

Everything CUAD-specific is contained here - the offsets, the identifier format,
the byte-order mark in the CSV, the prefixes repeated inside its cells. Downstream
code sees only the normalised records in ``models.py``.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from typing import Any

from rag_eval.dataset.models import Category, ClauseLabel, Span
from rag_eval.errors import DatasetError

_SLUG_STRIP = re.compile(r"[^A-Za-z0-9]+")
_SLUG_SQUEEZE = re.compile(r"-{2,}")
_CELL_PREFIX = re.compile(r"^(Category|Description|Answer Format|Group)\s*:\s*")


def slugify(title: str) -> str:
    """Turn a contract title into a filesystem-safe, stable identifier."""
    slug = _SLUG_SQUEEZE.sub("-", _SLUG_STRIP.sub("-", title)).strip("-").lower()
    if not slug:
        raise DatasetError("contract title", [f"{title!r} contains no usable characters"])
    return slug


def parse_contracts(
    raw: bytes,
) -> tuple[tuple[tuple[str, str, str], ...], tuple[ClauseLabel, ...]]:
    """Read CUAD's JSON into contracts and clause labels.

    Returns a tuple of ``(contract_id, title, text)`` triples alongside the labels.

    Raises:
        DatasetError: if the structure is unexpected, two contracts collide on an
            identifier, or any answer offset does not point at the text it claims to.
            All problems of a kind are collected and reported together.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatasetError("CUAD JSON", [f"is not valid JSON: {exc}"]) from exc

    entries = document.get("data") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise DatasetError("CUAD JSON", ["has no non-empty 'data' list at the top level"])

    contracts: list[tuple[str, str, str]] = []
    labels: list[ClauseLabel] = []
    problems: list[str] = []

    for position, entry in enumerate(entries):
        title = entry.get("title") if isinstance(entry, dict) else None
        paragraphs = entry.get("paragraphs") if isinstance(entry, dict) else None
        if not isinstance(title, str) or not title or not isinstance(paragraphs, list):
            problems.append(f"entry {position}: missing a title or paragraphs")
            continue
        if len(paragraphs) != 1:
            problems.append(f"{title}: expected exactly one paragraph, found {len(paragraphs)}")
            continue

        paragraph = paragraphs[0]
        text = paragraph.get("context")
        questions = paragraph.get("qas")
        if not isinstance(text, str) or not text or not isinstance(questions, list):
            problems.append(f"{title}: paragraph has no context text or no questions")
            continue

        contract_id = slugify(title)
        contracts.append((contract_id, title, text))
        labels.extend(_labels_for(contract_id, title, text, questions, problems))

    _reject_duplicate_ids(contracts, problems)
    if problems:
        raise DatasetError("CUAD JSON", problems)
    return tuple(contracts), tuple(labels)


def _labels_for(
    contract_id: str,
    title: str,
    text: str,
    questions: list[Any],
    problems: list[str],
) -> list[ClauseLabel]:
    """Build one label per question, verifying every offset against the contract text."""
    built: list[ClauseLabel] = []
    for question in questions:
        if not isinstance(question, dict) or not isinstance(question.get("id"), str):
            problems.append(f"{title}: a question is missing its id")
            continue

        category = question["id"].rsplit("__", 1)[-1]
        present = not question.get("is_impossible", False)
        spans: list[Span] = []

        for answer in question.get("answers") or []:
            start = answer.get("answer_start")
            span_text = answer.get("text")
            if not isinstance(start, int) or not isinstance(span_text, str) or not span_text:
                problems.append(f"{title}/{category}: an answer is missing its offset or text")
                continue
            end = start + len(span_text)
            if text[start:end] != span_text:
                # The single most important check in this file. If offsets drift,
                # every retrieval score built on them is quietly wrong.
                problems.append(
                    f"{title}/{category}: offset {start} points at "
                    f"{text[start:end][:40]!r}, not {span_text[:40]!r}"
                )
                continue
            spans.append(Span(start=start, end=end, text=span_text))

        if present and not spans:
            problems.append(f"{title}/{category}: answerable but no usable span survived")
            continue
        built.append(
            ClauseLabel(
                contract_id=contract_id,
                category=category,
                present=present,
                spans=tuple(spans),
            )
        )
    return built


def _reject_duplicate_ids(contracts: list[tuple[str, str, str]], problems: list[str]) -> None:
    """Two contracts sharing an identifier would overwrite each other on disk."""
    counts = Counter(contract_id for contract_id, _, _ in contracts)
    for contract_id, count in counts.items():
        if count > 1:
            problems.append(f"{contract_id}: {count} contracts share this identifier")


def parse_categories(raw: bytes) -> tuple[Category, ...]:
    """Read the category description CSV.

    The file carries a byte-order mark and repeats its column name inside each cell
    ("Category: Governing Law"), both of which are stripped here.
    """
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise DatasetError("category CSV", ["contains no rows"])

    categories: list[Category] = []
    for row in rows:
        values = {
            (key or "").strip(): _CELL_PREFIX.sub("", (value or "").strip())
            for key, value in row.items()
        }
        name = values.get("Category (incl. context and answer)", "")
        if not name:
            continue
        categories.append(
            Category(
                name=name,
                description=values.get("Description", ""),
                answer_format=values.get("Answer Format", ""),
                group=values.get("Group", ""),
            )
        )
    if not categories:
        raise DatasetError("category CSV", ["no rows carried a category name"])
    return tuple(categories)


def reconcile_category_names(
    labels: tuple[ClauseLabel, ...], categories: tuple[Category, ...]
) -> tuple[ClauseLabel, ...]:
    """Align label category names with the descriptions, and require full coverage.

    CUAD names each category twice, and the two spellings disagree. The question
    identifiers in the JSON are mechanically title-cased - "Ip Ownership Assignment",
    "Cap On Liability" - while the CSV carries the spelling a person wrote: "IP
    Ownership Assignment", "Cap on Liability". Matching is therefore done ignoring
    case, and the CSV spelling wins, because it is the one a reader would expect to
    see in a report.

    Raises:
        DatasetError: if two categories differ only by case, or if a category used by
            the labels has no description. Phase 3 turns these descriptions into
            natural questions, so a missing one would quietly become a weaker test case.
    """
    canonical: dict[str, str] = {}
    collisions: list[str] = []
    for category in categories:
        key = category.name.casefold()
        if key in canonical and canonical[key] != category.name:
            collisions.append(f"{canonical[key]!r} and {category.name!r} differ only by case")
        canonical[key] = category.name
    if collisions:
        raise DatasetError("category CSV", collisions)

    aligned: list[ClauseLabel] = []
    missing: set[str] = set()
    for label in labels:
        name = canonical.get(label.category.casefold())
        if name is None:
            missing.add(label.category)
            continue
        aligned.append(
            label if name == label.category else label.model_copy(update={"category": name})
        )
    if missing:
        raise DatasetError(
            "category CSV",
            [f"no description for category {name!r}" for name in sorted(missing)],
        )
    return tuple(aligned)

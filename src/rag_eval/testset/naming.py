"""Turning a filing title into a name a question can use.

CUAD's titles are filing identifiers — "GALERATHERAPEUTICS,INC_02_14_2020-EX-99.A-JOINT
FILING AGREEMENT", or "LejuHoldingsLtd_20140121_DRS (on F-1)_EX-10.26_8473102_EX-10.26_
Content License Agreement1" — which no one would write in a question. A question has to
name the contract it asks about, because retrieval searches all 510 at once, so the name
must be readable and must identify exactly one contract.

The trailing digit some titles carry ("Agreement1", "Agreement2") is not noise: it
distinguishes two different exhibits from the same filing, so it is kept and made
readable rather than stripped.
"""

from __future__ import annotations

import re

from rag_eval.errors import DatasetError

_EXHIBIT_MARKER = re.compile(r"EX-\d[\dA-Za-z.]*[-_]")
"""An exhibit marker such as "EX-10.11_" or "EX-99.A-". The number must start with a
digit and the character class excludes underscores, so the pattern cannot run on past
the marker and swallow the start of the document type — which it did, turning
"Co-Branding Agreement" into "Branding Agreement"."""
_LEADING_NUMBER = re.compile(r"^[\d.]+[-_\s]+")
_TRAILING_INDEX = re.compile(r"(?<=[a-z])(\d+)$", re.IGNORECASE)
_YEAR = re.compile(r"(19|20)\d{2}")
_SEPARATORS = re.compile(r"[_\s]+")
_DATE_TAIL = re.compile(r"[_\s-]*\d{1,8}([_\s-]\d{1,4})*$")


def _tidy(text: str) -> str:
    """Normalise separators and casing without losing information."""
    cleaned = _SEPARATORS.sub(" ", text).strip(" -_")
    return re.sub(r"\s*,\s*", ", ", cleaned.title())


def display_name(title: str) -> str:
    """Build a readable contract name from a filing title."""
    markers = list(_EXHIBIT_MARKER.finditer(title))
    stripped = title[markers[-1].end() :] if markers else title
    kind = _LEADING_NUMBER.sub("", stripped.strip(" -_"))

    index = _TRAILING_INDEX.search(kind)
    if index:
        kind = f"{kind[: index.start()]} (no. {index.group(1)})"
    kind = _tidy(kind) or "Agreement"

    head = title.split("_", 1)[0]
    company = _tidy(_DATE_TAIL.sub("", head))

    if not company or kind.lower().startswith(company.lower()):
        return f"the {kind}"
    return f"the {company} {kind}"


def unique_display_names(titles: dict[str, str]) -> dict[str, str]:
    """Map contract ids to distinct readable names.

    Where two contracts would share a name, the filing year is added to tell them
    apart, and failing that an ordinal, assigned in sorted order so it is stable
    between runs.

    Raises:
        DatasetError: if two contracts remain indistinguishable, which would make any
            question naming them ambiguous and the case unanswerable as posed.
    """
    proposed = {cid: display_name(title) for cid, title in titles.items()}
    counts = _counts(proposed)

    resolved: dict[str, str] = {}
    for contract_id, name in proposed.items():
        if counts[name] > 1:
            year = _YEAR.search(titles[contract_id])
            name = f"{name} ({year.group()})" if year else name
        resolved[contract_id] = name

    counts = _counts(resolved)
    for name, count in counts.items():
        if count == 1:
            continue
        sharing = sorted(cid for cid, value in resolved.items() if value == name)
        for position, contract_id in enumerate(sharing, start=1):
            resolved[contract_id] = f"{name} [{position} of {count}]"

    duplicates = sorted({n for n, c in _counts(resolved).items() if c > 1})
    if duplicates:
        raise DatasetError(
            "contract names",
            [f"{name!r} would identify more than one contract" for name in duplicates[:10]],
        )
    return resolved


def _counts(names: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in names.values():
        counts[name] = counts.get(name, 0) + 1
    return counts

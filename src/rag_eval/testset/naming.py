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


def ensure_unique(names: dict[str, str], titles: dict[str, str]) -> dict[str, str]:
    """Make a set of proposed contract names distinct, without re-deriving them.

    Takes names that are already final and only resolves collisions: first by adding
    the filing year, then by an ordinal assigned in sorted order so it is stable
    between runs. Kept separate from deriving a name because feeding a finished name
    back through the deriver mangles it — which is exactly what happened once,
    producing "the The Beijing Sina ..." and re-title-casing "SINA".

    Raises:
        DatasetError: if two contracts remain indistinguishable, which would make any
            question naming them ambiguous and the case unanswerable as posed.
    """
    counts = _counts(names)
    resolved: dict[str, str] = {}
    for contract_id, name in names.items():
        if counts[name] > 1:
            year = _YEAR.search(titles.get(contract_id, ""))
            name = f"{name} ({year.group()})" if year else name
        resolved[contract_id] = name

    for name, count in _counts(resolved).items():
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


def unique_display_names(titles: dict[str, str]) -> dict[str, str]:
    """Derive distinct names from filing titles alone. Used where annotations are absent."""
    return ensure_unique({cid: display_name(title) for cid, title in titles.items()}, titles)


def _counts(names: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in names.values():
        counts[name] = counts.get(name, 0) + 1
    return counts


_CORPORATE = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|company|co|plc|gmbh|ag|sa|nv|bv|lp|llp)\b\.?",
    re.IGNORECASE,
)
_NOISE = re.compile(r"^[\s(\"']|parties|referred|hereinafter|foregoing|collectively", re.IGNORECASE)
_PLACEHOLDER = frozenset(
    {
        "company",
        "consultant",
        "contractor",
        "customer",
        "distributor",
        "licensee",
        "licensor",
        "party",
        "purchaser",
        "recipient",
        "reseller",
        "seller",
        "supplier",
        "vendor",
    }
)
"""Words a contract uses instead of naming a party. "The Company Services Agreement"
identifies nothing, so a span that reduces to one of these is not a usable name."""
_LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)


def _readable(text: str) -> str:
    """Soften shouting without mangling names that already carry their own casing."""
    collapsed = _SEPARATORS.sub(" ", text).strip(" \"'(),.")
    letters = [c for c in collapsed if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return collapsed.title()
    return collapsed


def _best_party(spans: tuple[str, ...]) -> str:
    """Choose the span most likely to be an entity name rather than prose.

    CUAD's "Parties" annotation captures whatever identifies the signatories, which is
    sometimes a clean company name and sometimes a fragment of the sentence that
    introduces them. Preferring a corporate suffix picks out the former.
    """
    candidates = [
        _readable(span)
        for span in spans
        if span.strip() and not _NOISE.match(span.strip()) and len(span.strip()) <= 60
    ]
    candidates = [
        stripped
        for candidate in candidates
        if len(stripped := _LEADING_THE.sub("", candidate)) >= 3
        and stripped.lower().strip(".,") not in _PLACEHOLDER
    ]
    if not candidates:
        return ""
    with_suffix = [candidate for candidate in candidates if _CORPORATE.search(candidate)]
    pool = with_suffix or candidates
    return min(pool, key=lambda candidate: (len(candidate), candidate))


def name_from_annotations(
    document_name: tuple[str, ...], parties: tuple[str, ...], fallback: str
) -> str:
    """Name a contract using words that actually appear inside it.

    A name derived from the filing identifier is unusable for retrieval: identifiers
    squash the company into one token ("lejuholdingsltd") that appears nowhere in the
    corpus, so the only part of a question capable of identifying the right contract
    matches nothing and search returns generic passages from arbitrary documents. The
    expert annotations give us what the contract calls itself and who signed it, both
    of which are quotations from the text.

    Falls back to the filing title when a contract lacks the annotations.
    """
    title = _readable(document_name[0]) if document_name else ""
    party = _best_party(parties)
    if title and party:
        return f"the {party} {title}"
    if title:
        return f"the {title}"
    return fallback

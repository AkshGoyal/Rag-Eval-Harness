"""Measuring whether a question gives away its own answer.

A question containing its answer makes retrieval look good while testing nothing:
the system can succeed without finding the right passage, so every configuration
scores the same and an A/B comparison shows no difference where a real one exists.

The phrasings are written without anyone ever seeing an answer, so this cannot
happen by accident in the wording. It can still happen through the contract's name:
asking "who are the parties to the Galera Therapeutics joint filing agreement" hands
over one of the parties. That is what this measures.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

_COMMON = frozenset(
    {
        "about",
        "after",
        "against",
        "agreement",
        "all",
        "also",
        "and",
        "any",
        "are",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "can",
        "contract",
        "could",
        "date",
        "does",
        "doing",
        "done",
        "during",
        "each",
        "either",
        "for",
        "from",
        "further",
        "given",
        "had",
        "has",
        "have",
        "having",
        "here",
        "how",
        "into",
        "its",
        "itself",
        "more",
        "most",
        "not",
        "now",
        "only",
        "other",
        "our",
        "out",
        "over",
        "own",
        "party",
        "same",
        "shall",
        "she",
        "should",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "upon",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "within",
        "would",
        "year",
        "years",
    }
)


def distinctive_words(text: str) -> frozenset[str]:
    """Words long and rare enough to identify a particular answer."""
    return frozenset(
        word for word in _WORD.findall(text.lower()) if len(word) > 3 and word not in _COMMON
    )


def answer_overlap(question: str, reference_answer: str) -> float:
    """Share of the answer's distinctive words that already appear in the question.

    Returns 0.0 when the answer has no distinctive words of its own - "Yes." and
    "No." carry none, so an existence question cannot leak by this measure.
    """
    answer_words = distinctive_words(reference_answer)
    if not answer_words:
        return 0.0
    return len(answer_words & distinctive_words(question)) / len(answer_words)

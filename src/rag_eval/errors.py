"""Exceptions raised deliberately by this package.

Every error here is one we chose to raise, with a message naming where the problem
is. Bad input fails loudly at the boundary rather than producing a plausible-looking
number further downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class RagEvalError(Exception):
    """Base class for errors this package raises on purpose."""


class ConfigError(RagEvalError):
    """A configuration file could not be read, parsed, or validated.

    Carries the offending file and one entry per problem found, so a config with
    three mistakes reports all three rather than only the first.
    """

    def __init__(self, path: Path, problems: Sequence[str]) -> None:
        """Build the error from the file it concerns and the problems found in it."""
        self.path = path
        self.problems: list[str] = list(problems)
        detail = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(f"Invalid configuration {path}:\n{detail}")

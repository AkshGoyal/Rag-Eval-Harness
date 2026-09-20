"""Loading the hand-written question phrasings."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rag_eval.errors import ConfigError
from rag_eval.hashing import sha256_of


class Style(StrEnum):
    """Whether a category asks for a value or asks whether a clause exists."""

    EXTRACTION = "extraction"
    EXISTENCE = "existence"


class Template(BaseModel):
    """The phrasings available for one clause category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1)
    style: Style
    phrasings: tuple[str, ...] = Field(min_length=1)


class TemplateSet(BaseModel):
    """Every category's phrasings, loaded from disk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    templates: tuple[Template, ...] = Field(min_length=1)

    def by_category(self) -> dict[str, Template]:
        """Index the templates by the category they serve."""
        return {template.category: template for template in self.templates}

    def content_hash(self) -> str:
        """Fingerprint the phrasings, so a reworded question changes the test set's identity."""
        return sha256_of(self.model_dump(mode="json"))


def load_templates(path: Path) -> TemplateSet:
    """Read and validate the template file.

    Raises:
        ConfigError: if the file is missing, malformed, or a phrasing lacks the
            ``{contract}`` placeholder - which would produce a question that never
            says which contract it is about.
    """
    if not path.is_file():
        raise ConfigError(path, ["is missing"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"is not valid YAML: {exc}"]) from exc

    try:
        templates = TemplateSet.model_validate(data)
    except Exception as exc:
        raise ConfigError(path, [str(exc)]) from exc

    problems = [
        f"{template.category!r} phrasing {index} has no {{contract}} placeholder"
        for template in templates.templates
        for index, phrasing in enumerate(template.phrasings)
        if "{contract}" not in phrasing
    ]
    seen = [template.category for template in templates.templates]
    problems += [
        f"{category!r} appears more than once" for category in seen if seen.count(category) > 1
    ]
    if problems:
        raise ConfigError(path, sorted(set(problems)))
    return templates

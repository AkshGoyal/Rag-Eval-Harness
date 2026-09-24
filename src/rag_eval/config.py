"""The configuration model: everything that can change a RAG system's answers.

A "configuration" is the unit this harness compares. Two runs differing in one
field here are the A and B of an A/B comparison, so the model has three properties
that matter more than they might appear:

* ``extra="forbid"`` - an unrecognised field is an error, not a silent default.
  Without this, ``top_K: 10`` (wrong case) would be ignored, the run would use the
  default, and an A/B comparison of two identical configurations would report
  "no regression found" with complete confidence.
* ``frozen=True`` - a configuration cannot change after loading, so the hash
  recorded in a run manifest stays true for the whole run.
* enumerated fields - an invalid strategy or provider is unrepresentable rather
  than discovered halfway through a run.

Enumerations list only what is implemented. ``hybrid`` retrieval is planned (see
docs/ROADMAP.md) and deliberately absent until it works: a configuration file should
not offer a setting that fails.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from pydantic_core import ErrorDetails

from rag_eval.errors import ConfigError
from rag_eval.hashing import sha256_of


class _Section(BaseModel):
    """Base for configuration sections: immutable, and strict about unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ChunkStrategy(StrEnum):
    """How documents are split before embedding."""

    FIXED_CHAR = "fixed_char"
    """Fixed-length pieces measured in characters, cut at word boundaries.

    Characters rather than tokens because tokenising needs either a runtime download
    or a heavy dependency, and this suite runs with no network. English prose is
    roughly four characters to a token, so 2,000 characters is about 500 tokens."""


class RetrievalMethod(StrEnum):
    """How candidate chunks are found for a question."""

    BM25 = "bm25"
    """Keyword search. Needs no model, so it runs offline and free."""

    DENSE = "dense"
    """Vector search: meaning, not matching words. Needs the embedding model."""


_ALIAS = re.compile(r"^~|-latest$|:latest$")


def _fixed_model_id(value: str) -> str:
    """Reject a model id that is an alias the gateway can re-point.

    Ids such as "~deepseek/deepseek-v4-flash-latest" are pointers the gateway can
    move to a newer model without notice. Two runs of one configuration would then
    call different models, and the difference between them would be unattributable.
    """
    if _ALIAS.search(value):
        raise ValueError(
            f"{value!r} is an alias the gateway can re-point to a different model; "
            "name a fixed model instead"
        )
    if "/" not in value:
        raise ValueError(
            f"{value!r} is not a gateway model id; expected vendor/model, "
            "for example openai/text-embedding-3-small"
        )
    return value


ModelId = Annotated[str, Field(min_length=3), AfterValidator(_fixed_model_id)]
"""A gateway model id, such as ``meta-llama/llama-3.1-8b-instruct``. Never an alias."""

UpstreamProvider = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Pin calls to this upstream provider, as the gateway names it (for example "
            "'OpenAI' or 'Novita'). Unpinned, the gateway picks whichever is cheapest "
            "or fastest at that moment."
        ),
    ),
]


class CorpusConfig(_Section):
    """Which document set the run indexes, and at which version."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    hash: str | None = Field(
        default=None,
        description="Content hash of the ingested corpus. Filled by ingestion; null until then.",
    )


class ChunkingConfig(_Section):
    """How documents are split into retrievable units."""

    strategy: ChunkStrategy
    size: int = Field(ge=1, description="Chunk length in characters.")
    overlap: int = Field(ge=0, description="Characters shared between adjacent chunks.")

    @model_validator(mode="after")
    def _overlap_must_be_smaller_than_size(self) -> ChunkingConfig:
        """Reject an overlap that would stop the chunker advancing through a document."""
        if self.overlap >= self.size:
            raise ValueError(
                f"overlap ({self.overlap}) must be smaller than size ({self.size}); "
                "an overlap at or above the chunk size never advances through the document"
            )
        return self


class EmbeddingConfig(_Section):
    """The model that turns chunks and questions into vectors."""

    model: ModelId
    provider: UpstreamProvider = None
    batch_size: int = Field(
        default=100,
        ge=1,
        le=512,
        description="Chunks sent per request when building an index.",
    )
    allow_mixed_providers: bool = Field(
        default=False,
        description=(
            "Accept an index whose vectors came from more than one upstream host. Off by "
            "default: hosts can run the same model at different numeric precision, so "
            "their vectors are not guaranteed to be comparable."
        ),
    )


class RetrievalConfig(_Section):
    """How many chunks are retrieved, and by what method."""

    method: RetrievalMethod
    top_k: int = Field(ge=1, description="Number of chunks passed to the generator.")


class GenerationConfig(_Section):
    """The model that answers a question from retrieved context."""

    model: ModelId
    provider: UpstreamProvider = None
    prompt: str = Field(min_length=1, description="Path to the versioned prompt file.")
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(ge=1)


class JudgeConfig(_Section):
    """The model that scores an answer, and the rubric it scores against."""

    model: ModelId
    provider: UpstreamProvider = None
    rubric: str = Field(min_length=1, description="Path to the versioned rubric file.")
    max_output_tokens: int = Field(ge=1)


class RunConfig(_Section):
    """One complete, comparable RAG configuration."""

    name: str = Field(min_length=1, description="Label for this configuration. Not an input.")
    corpus: CorpusConfig
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    judge: JudgeConfig

    def content_hash(self) -> str:
        """Hash every setting that can change this configuration's answers.

        ``name`` is excluded because it is a label, not an input: two configurations
        differing only in name produce identical answers, so they must share a cache
        entry and compare as identical. Every other field is included, including the
        corpus hash, because changing the documents changes the answers.
        """
        payload: dict[str, Any] = self.model_dump(mode="json")
        payload.pop("name")
        return sha256_of(payload)


def _describe(error: ErrorDetails) -> str:
    """Render one pydantic error as ``field.path: message``."""
    location = ".".join(str(part) for part in error["loc"]) or "<root>"
    return f"{location}: {error['msg']}"


def load_config(path: str | Path) -> RunConfig:
    """Load and validate a configuration file.

    Raises:
        ConfigError: if the file cannot be read, is not valid YAML, or does not
            satisfy the schema. The message names the file and every field at fault.
    """
    file_path = Path(path)

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(file_path, [f"cannot be read: {exc.strerror or exc}"]) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(file_path, [f"is not valid YAML: {exc}"]) from exc

    if data is None:
        raise ConfigError(file_path, ["is empty"])
    if not isinstance(data, dict):
        raise ConfigError(
            file_path,
            [f"must be a mapping at the top level, found {type(data).__name__}"],
        )

    try:
        return RunConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(file_path, [_describe(err) for err in exc.errors()]) from exc

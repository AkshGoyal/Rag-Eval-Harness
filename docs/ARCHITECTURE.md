# Architecture

How the harness is put together: what each piece owns, how information moves through it,
and what it depends on from outside.

**Status:** early. Only the configuration layer exists. Sections fill in as the pieces
they describe get built, so that nothing here is written speculatively.

---

## 1. What exists today

A configuration file describes one complete RAG setup — which documents, how they are
split, which models, how many chunks to retrieve. It is the unit the harness compares:
an A/B comparison is two of these files differing in one field.

| Piece | What it owns | What it deliberately does not own | Where it lives |
|---|---|---|---|
| Configuration model | The shape of a valid configuration, and rejecting invalid ones at load time | Knowing what any setting *does* — it validates, it does not act | `src/rag_eval/config.py` |
| Content hashing | Turning a structure into a stable fingerprint that depends on content alone | Deciding what gets hashed | `src/rag_eval/hashing.py` |
| Errors | Carrying enough context to locate a problem — which file, which field | Recovering from anything | `src/rag_eval/errors.py` |

## 2. Data flow

Today there is one path, and it is short:

```
configs/baseline.yaml
        │
        ▼
  load_config()          reads the file, parses YAML, validates every field
        │
        ├── on success → RunConfig, immutable, with .content_hash()
        └── on failure → ConfigError naming the file and every bad field
```

The hash is the part that matters later. It is a fingerprint of every setting that can
change the answers, computed from content rather than from the file's bytes, so the same
configuration written with its sections in a different order produces the same
fingerprint. Two things will depend on that: the run manifest, which records which
configuration produced which numbers, and the response cache, which must recognise that a
changed setting means a changed question.

The configuration's `name` is excluded from the fingerprint on purpose. It is a label,
not an input — renaming a configuration does not change a single answer it produces.

## 3. Diagram

To be drawn once there is more than one path through the system. A diagram of three
modules would be decoration.

## 4. Module map

```
src/rag_eval/
  config.py     the configuration model and its loader
  hashing.py    canonical serialisation and content fingerprints
  errors.py     the errors this package raises on purpose
configs/
  baseline.yaml the starting configuration, the "A" of every comparison
tests/
  fixtures/     small configuration files, mostly deliberately broken
```

## 5. External dependencies

| Dependency | Used for | Pinned | If it were unavailable |
|---|---|---|---|
| pydantic | Validating configuration and rejecting bad input at load | Lockfile | Validation would be hand-written; the failure modes would move from loud to quiet |
| pyyaml | Reading configuration files | Lockfile | Configuration format would change, not the design |
| pytest, ruff, mypy | Tests, linting and formatting, type checking | Lockfile | Development friction only; nothing at runtime |

No network calls, no credentials, and no model providers are reachable from the code yet.
Those arrive with the provider wrapper, which is the single place every model call will
pass through.

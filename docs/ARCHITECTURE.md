# Architecture

How the harness is put together: what each piece owns, how information moves through it,
and what it depends on from outside.

**Status:** early. The configuration, dataset and test-set layers exist. Nothing yet
retrieves, generates or judges. Sections fill in as the pieces
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
| Corpus reader | Knowing what CUAD's published format looks like | Anything downstream — this is the only file that knows | `src/rag_eval/dataset/cuad.py` |
| Ingestion | Fetching, verifying and writing a normalised dataset | Interpreting the contents | `src/rag_eval/dataset/ingest.py` |
| Dataset loader | Reading a dataset back and proving it is unchanged | Chunking or embedding it | `src/rag_eval/dataset/loader.py` |
| Dataset models | What a contract, a label and a manifest are | Where they came from | `src/rag_eval/dataset/models.py` |
| Question templates | The phrasings used to ask about each clause category | Which cases get built | `testset/templates.yaml` |
| Contract naming | Turning a filing title into a name a question can use | Uniqueness policy beyond its own checks | `src/rag_eval/testset/naming.py` |
| Leakage check | Measuring whether a question gives away its answer | Deciding what to do about it | `src/rag_eval/testset/leakage.py` |
| Test set builder | Selecting cases reproducibly from a corpus | Knowing how the corpus was loaded — it takes a protocol | `src/rag_eval/testset/build.py` |

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

### Ingestion

```
CUAD archive (HTTPS)
        │   checked against a recorded fingerprint
        ▼
  CUADv1.json  ──►  parse, verifying every answer offset against the contract text
        │
        ▼
data/cuad/v1/
  contracts/*.txt     510 contracts, one file each
  contracts.jsonl     index: id, title, sha256, length
  labels.jsonl        20,910 rows; 6,702 with answer spans, 14,208 expert absences
  categories.json     41 clause categories and their descriptions
  manifest.json       source, counts, fingerprint, timestamp
```

The manifest's fingerprint covers the contract hashes, the labels and the categories.
The timestamp is recorded but excluded from it, so ingesting the same data twice gives
the same fingerprint. `verify` re-hashes every contract file and recomputes the
fingerprint, which is what catches documents shifting underneath a comparison.

### Building a test set

```
data/cuad/v1  +  testset/templates.yaml  +  seed
        │
        ▼
  classify each label      extraction vs existence, answerable vs not
  rank deterministically   sha256(seed | contract | category)
  fill a phrasing          chosen by the same rank, so it is stable
  measure answer overlap   reject at or above 0.5, and count the rejections
  cap cases per contract   no document dominates the score
        │
        ▼
testset/seed-v1.jsonl + seed-v1.manifest.json
```

The builder takes a `CorpusView` protocol rather than the concrete loaded dataset, so it
does not depend on how the corpus arrived. That is the seam an external system will come
through in Phase 14.

## 3. Diagram

To be drawn once retrieval and generation exist and there is a full run to depict.

## 4. Module map

```
src/rag_eval/
  __main__.py   command line: `python -m rag_eval ingest|verify|build-testset`
  config.py     the configuration model and its loader
  hashing.py    canonical serialisation and content fingerprints
  errors.py     the errors this package raises on purpose
  dataset/
    models.py   what a contract, label, span and manifest are
    cuad.py     the only file that knows CUAD's published format
    ingest.py   fetch, verify, normalise, write
    loader.py   read back and prove unchanged
  testset/
    models.py   what a test case is, and the five case types
    templates.py  loading the hand-written phrasings
    naming.py   filing title -> a name a question can use
    leakage.py  does the question give away its answer?
    build.py    reproducible, stratified case selection
testset/
  templates.yaml        82 phrasings, 41 categories — the file to review
  seed-v1.jsonl         the 30 committed cases
  seed-v1.manifest.json how they were built, and from what
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

Ingestion makes one HTTPS download, using only the standard library. No credentials and
no model providers are reachable from the code yet.
Those arrive with the provider wrapper, which is the single place every model call will
pass through.

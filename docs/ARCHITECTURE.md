# Architecture

How the harness is put together: what each piece owns, how information moves through it,
and what it depends on from outside.

**Status:** the configuration, dataset, test-set, retrieval and model-call layers
exist. No model has actually been called yet — that needs a key, and the development
environment has none. Sections fill in as the pieces
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
| Chunking | Splitting contracts into retrievable pieces at word boundaries | Deciding how big a chunk should be — that is configuration | `src/rag_eval/pipeline/chunking.py` |
| BM25 index | Ranking chunks by keyword match, exactly and deterministically | Understanding meaning — it matches words, not ideas | `src/rag_eval/retrieval/bm25.py` |
| Dense index | Embedding chunks once, saving them under a content key, exact cosine search | Choosing the model — that is configuration | `src/rag_eval/retrieval/dense.py` |
| Hybrid merge | Combining rankings from several retrievers by rank (reciprocal rank fusion) | How any one ranking is produced | `src/rag_eval/retrieval/hybrid.py` |
| Retrieval metrics | hit@k, span recall@k and MRR per case type, with errors and unscored cases counted | Anything about generated answers | `src/rag_eval/metrics/retrieval.py` |
| `retrieve` command | Running one configuration's retrieval against the test set and printing the report | Comparing two runs — that comes next | `src/rag_eval/retrieval_run.py` |
| Model client | Every call to every model: caching, retries, spend limit, provider pinning | Knowing what a prompt means — it moves requests, not intent | `src/rag_eval/llm/client.py` |
| Response cache | Storing raw provider responses against a content key | Deciding what belongs in the key — the request models do that | `src/rag_eval/llm/cache.py` |
| Budget guard | Stopping a run before it exceeds its spending limit | Estimating cost in advance | `src/rag_eval/llm/budget.py` |
| Transport | One HTTP POST | Anything else — it exists so the rest can be tested offline | `src/rag_eval/llm/transport.py` |

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

### Retrieval

```
contracts + chunking config
        │
        ▼
  chunk_text()            fixed character budget, cut at whitespace
        │                 15,444 chunks at the 2,000-character default
        ▼
  BM25Index               inverted index: word -> chunks containing it
        │                 a dense chunk-by-word matrix would need ~3 GB
        ▼
  search(question, k)     exact scoring, ties broken by document order
        │
        ▼
  Retrieved(rank, score, chunk)
```

Chunks carry their character offsets into the contract, so a retrieved chunk can be
checked against a gold answer span directly. Any overlap counts as finding it: an answer
split by a chunk boundary is still partly present in both, and scoring that as a miss
would understate what the retriever did.

Retrieval is exact — every chunk is scored on every query — which is what allows a score
difference to be attributed to a configuration change rather than to an index that
varies between builds.

### A model call

```
ChatRequest / EmbeddingRequest
  model, messages, prompt_version, temperature, max_tokens, provider
        │
        ▼
  cache key = sha256 of the whole request
        │
        ├── hit  → cached response, zero cost, recorded as a hit
        │
        └── miss → budget check → HTTP POST (provider pinned, fallback off)
                       │
                       ├── 200        → cache it, record usage, cost, provider served
                       ├── 429 / 5xx  → wait and retry, counting attempts
                       └── 4xx        → stop; repeating a malformed request wastes money
        │
        ▼
  Result + CallRecord
    cache_hit, attempts, provider_requested, provider_served,
    usage, cost_usd, truncated, latency, error
```

Everything in that record exists because leaving it out would let a number look sound
when it is not. `truncated` marks an answer cut off at the output limit, so it is never
scored as though the model chose to stop. `provider_served` catches the gateway quietly
routing to a different upstream. `attempts` above one means the provider was unstable,
which is invisible if retries are silent.

The cache is the part most worth distrusting: a key that fails to change when an input
changes returns an old answer under a new configuration's name, and nothing about the
output looks wrong. Six separate tests assert that each field capable of changing an
answer also changes the key.

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
  pipeline/
    chunking.py splitting a contract into retrievable pieces
    corpus.py   chunking every contract, in a stable order
  retrieval/
    base.py     what every retriever provides
    bm25.py     keyword search over an inverted index
    dense.py    vector search, saved under a content key
    hybrid.py   keyword + vector rankings merged by rank
  metrics/
    retrieval.py  hit@k, span recall@k, MRR
  retrieval_run.py  the `retrieve` command
  llm/
    types.py    what a model call is, and what it produced
    cache.py    content-addressed response cache
    budget.py   the hard spending limit
    transport.py  one HTTP POST, isolated so tests need no network
    client.py   the single boundary between this project and any provider
  testset/
    models.py   what a test case is, and the five case types
    templates.py  loading the hand-written phrasings
    naming.py   filing title -> a name a question can use
    leakage.py  does the question give away its answer?
    build.py    reproducible, stratified case selection
testset/
  templates.yaml        82 phrasings, 41 categories — the file to review
  seed-v2.jsonl         the 30 current cases (D-012)
  seed-v2.manifest.json how they were built, and from what
  seed-v1.*             the first set, kept because the first results used it
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
| numpy | Vectorised BM25 scoring | Lockfile | Scoring would be a Python loop: correct, much slower |
| pytest, ruff, mypy | Tests, linting and formatting, type checking | Lockfile | Development friction only; nothing at runtime |

Deliberately absent: a tokeniser. `tiktoken` downloads its vocabulary at first use, which
would put a network call inside a suite that must run offline. See D-009.

Ingestion makes one HTTPS download, using only the standard library. No credentials and
no model providers are reachable from the code yet.
Those arrive with the provider wrapper, which is the single place every model call will
pass through.

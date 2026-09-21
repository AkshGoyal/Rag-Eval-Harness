# rag-eval-harness

Evaluate a RAG configuration against a fixed test set, compare two configurations
case by case, and surface where one regressed.

Changing a RAG system — chunk size, embedding model, top-k, the generation prompt —
moves answer quality in ways that are invisible without measurement. Trying a few
questions by hand cannot detect that multi-hop questions got 15% worse while
single-fact questions improved slightly, which is exactly what configuration changes
do. This tool measures the difference between two configurations and localises it:
which category, which cases, and whether retrieval missed the source or the
generator misused good context.

## Status

**Phase 5 of 14.** The corpus, the test set, chunking and keyword retrieval all work
and need no credentials. Vector search, answer generation and judging are next, and
those need an API key. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the plan and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for why each choice was made.

## Getting started

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
uv run pytest            # 119 tests, no API key needed — CI enforces that
```

Then build the corpus and the test set. Both are reproducible: the same inputs always
produce the same fingerprints, which are printed so you can check.

```bash
uv run python -m rag_eval ingest         # downloads CUAD, ~18 MB, a few seconds
uv run python -m rag_eval verify         # proves nothing has changed since
uv run python -m rag_eval build-testset  # selects 30 cases from 20,910 candidates
```

Nothing above costs anything or needs a key.

## Using models

One key covers everything, through [OpenRouter](https://openrouter.ai/keys).

```bash
cp .env.example .env     # then paste your key after OPENROUTER_API_KEY=
```

`.env` is git-ignored and cannot be committed.

```bash
uv run python -m rag_eval models --search llama    # real prices, read from the gateway
uv run python -m rag_eval check-models             # two tiny calls; costs a fraction of a rupee
```

`check-models` proves the whole path works — key, models, provider pinning, cost
accounting — before anything is built on top of it. Run it twice: the second time both
calls come from the cache and cost nothing.

## Documentation

| Document | What it holds |
|---|---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phases, current step, fixed constraints |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every choice, its alternatives, and its risks |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, data flow, module map |
| [`docs/FAILURE_MAP.md`](docs/FAILURE_MAP.md) | If X breaks, look here |
| [`docs/EVAL_METHODOLOGY.md`](docs/EVAL_METHODOLOGY.md) | What each metric measures, and cannot |

## Licence

Not yet chosen. The corpus (CUAD) is CC BY 4.0; see `docs/DECISIONS.md` D-003.

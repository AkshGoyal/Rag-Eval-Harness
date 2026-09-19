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

**Phase 1 of 14 — early.** The configuration model and its tooling exist; the
pipeline, metrics, judge and reports do not yet. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for the plan and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for why each choice was made.

## Running the checks

Requires [uv](https://docs.astral.sh/uv/). **No API keys are needed** — the suite
runs without credentials, and CI enforces that.

```bash
uv sync --dev
uv run ruff check .
uv run mypy
uv run pytest
```

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

# Roadmap

**Current phase:** Phase 1 — Stack and model tier selection (in progress)
**Last updated:** 2026-09-19
**Next action:** decide the model tier for the reference pipeline's generator and judge
under the fixed ₹1000 total budget (D-005, pending). Corpus, scope, labelling budget
and provider are settled — see D-003, D-004 and the constraints below.

This is a proposal. Phases, their contents, and their order are all open to challenge
under §1.6 of `CLAUDE.md`.

---

## Progress

| Phase | Name | Status |
|-------|------|--------|
| 0 | Discovery and working agreement | **complete** (2026-09-19) |
| 1 | Repo home and stack selection | **in progress** — repo home settled (D-001); stack and model tier open |
| 2 | Corpus selection and ingestion | corpus chosen (D-003), ingestion not started |
| 3 | Seed test set (v0) | not started |
| 4 | Reference RAG pipeline | not started |
| 5 | Run harness core | not started |
| 6 | Retrieval metrics — **Milestone A** | not started |
| 7 | Test set v1 (full) | not started |
| 8 | Judge | not started |
| 9 | Judge calibration | not started |
| 10 | Single-run report — **Milestone B** | not started |
| 11 | A/B comparison and noise handling | not started |
| 12 | Worked example | not started |
| 13 | Docs, README, polish — **Milestone C** | not started |
| 14 | Adapter for an external RAG system | not started |

**Milestone A — walking skeleton.** One config runs end to end over a real corpus and
produces retrieval scores with a manifest. No LLM judge involved. First real signal.

**Milestone B — judged evaluation.** A single config is scored on retrieval *and*
generation, with the judge calibrated against human labels and the agreement number
written down.

**Milestone C — portfolio ready.** Definition of done in the brief is met.

---

## Fixed constraints

These are settled and bound every phase below. Changing one is a decision, not an
adjustment.

| Constraint | Value | Consequence |
|---|---|---|
| Total budget | **₹1000 (~$11–12), all costs** | Model tier is a budget decision, not a quality one. A hard in-code spend cap is required before the first uncached LLM call. |
| Aksh's manual labelling time | **30–60 minutes, total** | Test cases are derived from CUAD annotations and spot-checked, never hand-authored. Judge calibration gets one overall agreement number, not per-category. |
| Corpus | CUAD, CC BY 4.0 (D-003) | Retrieval labels come free from expert annotations. |
| Provider | OpenAI (Aksh's existing access) | Single provider behind the wrapper; swapping is a config change, not a rewrite. |
| Scope order | Generic harness, then adapter (D-004) | The harness never depends on any particular RAG system. |

### What the budget rules out

At GPT-4o rates a judged case costs roughly $0.03 all-in. ₹1000 buys about 380 of
them — a single two-config comparison over 100 cases, with nothing left for the
iteration, mistakes and repeated runs that the work actually requires. The generator
and judge therefore run on a cheap tier by default, and any escalation is paid for out
of a reserved slice and justified by calibration evidence rather than assumed.

The larger financial risk is not per-token price but accidental spend: a retry loop, or
re-indexing the full corpus repeatedly. That is what the Phase 5 budget cap and the
response cache exist to prevent, which raises their priority — **no uncached LLM call
should ever be made in this project.**

---

## Phases

### Phase 0 — Discovery and working agreement

- **Goal.** Shared understanding of the problem, the constraints, and the order of work.
  Persist the working agreement so it survives across sessions.
- **Main decisions.** None yet — this phase produces the question list, not answers.
- **Key risks.** Building on an assumption never checked (budget, provider access,
  labelling appetite); a corpus chosen for convenience that cannot show a regression.
- **Done when.** `CLAUDE.md` and the five docs exist; open questions are listed; the
  roadmap is agreed.

### Phase 1 — Repo home and stack selection

- **Goal.** Decide where the project lives and what it is built with, and set up a repo
  skeleton that fails loudly (linting, typing, test runner, no-keys test policy).
- **Main decisions.** Language and runtime; dependency manager; config format and
  validation library; test framework; vector store; whether any of this is pluggable.
- **Key risks.** Over-engineering the skeleton before there is anything to run; picking
  a vector store whose behaviour (approximate search, non-determinism) later
  contaminates the A/B signal; a stack Aksh would not choose to maintain himself.
- **Done when.** An empty repo runs `lint`, `typecheck`, `test` green in CI, with zero
  API keys present, and every choice has a `DECISIONS.md` entry.

### Phase 2 — Corpus selection and ingestion

- **Goal.** One public corpus, licensed for use in a public repo, ingested into a
  versioned, hashed, reproducible local dataset.
- **Main decisions.** Which corpus; how much of it; how documents are fetched and
  normalised; how the dataset is versioned and hashed; what is committed to git versus
  fetched by script.
- **Key risks.** Licence that forbids redistribution (mitigated by committing a fetch
  script plus hashes, not the documents); a corpus so well memorised by the generator
  that retrieval quality stops mattering — this would silently destroy the whole A/B
  premise; documents too short for chunking strategy to have any effect.
- **Done when.** `ingest` runs from a clean checkout, produces a dataset with a stable
  hash, and the licence is stated in `DECISIONS.md` and the README.

### Phase 3 — Seed test set (v0)

- **Goal.** A small, hand-checked set (roughly 20–30 cases) — just enough to drive the
  walking skeleton and expose test-set design problems early.
- **Main decisions.** Case schema; category taxonomy; authoring method; who verifies
  reference answers; how gold retrieval labels are recorded.
- **Key risks.** Writing 150 cases against a schema that turns out to be wrong; questions
  answerable from their own wording; categories whose boundaries two people would draw
  differently.
- **Done when.** Cases load with schema validation, every case has a verified reference
  answer and gold source IDs, and the leakage check has been run on all of them.

### Phase 4 — Reference RAG pipeline

- **Goal.** A minimal, fully config-driven RAG pipeline over the corpus: chunk → embed →
  index → retrieve → generate.
- **Main decisions.** Chunking strategy and its parameters; embedding model; retrieval
  method (dense, lexical, hybrid); generation prompt structure; the boundary of what
  counts as "configuration".
- **Key risks.** The pipeline becoming the project instead of the thing being measured;
  a config surface too narrow to produce an interesting A/B, or so wide it is untestable;
  hidden non-determinism making reruns non-reproducible.
- **Done when.** Two different config files produce demonstrably different answers for
  the same question, and every knob is in the config, not the code.

### Phase 5 — Run harness core

- **Goal.** The part that makes results trustworthy: manifest, cache, structured logs,
  budget cap, per-case error isolation.
- **Brought forward by the budget.** The cache and the spend cap must exist before the
  first uncached LLM call, not after Phase 4 is finished. With ₹1000 total, an
  unprotected retry loop is not an inconvenience, it is the end of the project.
- **Main decisions.** Manifest contents and format; cache key composition and storage;
  log schema; budget-cap behaviour on trip; how a per-case error is represented.
- **Key risks.** A cache key missing a field (stale results attributed to a new config —
  the most dangerous bug in this codebase); errors quietly dropped from denominators; a
  budget cap that stops mid-case and leaves inconsistent output.
- **Done when.** A run can be reproduced from its manifest alone; a deliberately broken
  case is recorded as an error without killing the run; a prompt edit provably misses the
  cache.

### Phase 6 — Retrieval metrics — *Milestone A*

- **Goal.** Deterministic retrieval scoring against gold source IDs, with no LLM in the
  loop.
- **Main decisions.** Which metrics (recall@k, precision@k, MRR, nDCG — and which are
  actually load-bearing); how a chunk maps back to a gold document; how refusal and
  out-of-scope cases are handled.
- **Key risks.** Metrics that look rigorous but are insensitive to the changes we care
  about; chunk-to-document attribution done wrong, silently inflating recall.
- **Done when.** Two configs can be compared on retrieval quality, end to end, from the
  command line — with unit tests on hand-built fixtures.

### Phase 7 — Test set v1 (full)

- **Goal.** Expand the seed set to a size where a per-category regression is visible
  above noise, using what Phases 3–6 taught us.
- **Main decisions.** Final size and per-category counts; how much is hand-written versus
  corpus-synthesised-then-verified; the review process for reference answers.
- **Key risks.** Categories too thin to support a per-category claim; a synthesis prompt
  that produces homogeneous, easy questions; effort spent before we know which categories
  actually discriminate between configs.
- **Done when.** Every category has enough cases for the noise rule from Phase 11 to have
  power, and `EVAL_METHODOLOGY.md` §3 is complete.

### Phase 8 — Judge

- **Goal.** LLM-as-judge with a versioned rubric, schema-validated output, and
  code-verified citations.
- **Main decisions.** Judge model; rubric design; output schema and enumerated verdicts;
  what the judge sees (question, answer, context, reference answer — or a subset);
  behaviour on validation failure.
- **Key risks.** Judge and generator sharing a model (self-preference); verbosity bias;
  a rubric that rewards style over correctness; fabricated citations passing because
  nothing checks them.
- **Done when.** Judge output validates against the schema, every cited span is verified
  to exist in the retrieved context, and a validation failure is recorded as an error
  rather than silently retried forever.

### Phase 9 — Judge calibration

- **Goal.** Establish how far the judge can be trusted, in a number.
- **Main decisions.** Sample size and sampling strategy for human labelling; the
  agreement statistic; the threshold below which we change the rubric rather than ship.
- **Key risks.** Calibrating on a sample too small or too easy; Aksh labelling after
  seeing the judge's verdict (anchoring); measuring agreement only in aggregate and
  missing that it collapses on one category.
- **Done when.** Agreement is measured, per category, documented in
  `EVAL_METHODOLOGY.md` §4, with the disagreement cases inspected.

### Phase 10 — Single-run report — *Milestone B*

- **Goal.** One readable report per run: scores overall and per category, error counts
  beside them, cost, latency, and a link back to the manifest.
- **Main decisions.** Output format; the split between machine-readable results and
  human-readable report; what appears at the top.
- **Key risks.** A report that shows a headline score without its error count; numbers
  that cannot be traced back to a manifest.
- **Done when.** A run produces a report Aksh can read without asking what a number means.

### Phase 11 — A/B comparison and noise handling

- **Goal.** Compare two runs case by case, and say honestly whether a delta is real.
- **Main decisions.** How runs are paired; the noise-estimation method (repeated runs,
  paired statistical test, bootstrap intervals) and its cost; how flips are presented.
- **Key risks.** Reporting a delta smaller than run-to-run variance as a regression —
  the single most embarrassing failure mode for an eval tool; unpaired comparison
  throwing away the variance reduction that pairing gives for free.
- **Done when.** A comparison report lists per-category deltas with an explicit
  noise verdict, and per-case flips with judge reasons and retrieved sources for both sides.

### Phase 12 — Worked example

- **Goal.** The design target: a real regression, caught and explained well enough to act
  on.
- **Main decisions.** Which config change to use; whether the regression is found or
  deliberately introduced, and how that is disclosed.
- **Key risks.** No honest regression appears and the temptation to manufacture one; a
  regression so obvious it demonstrates nothing.
- **Done when.** The README shows config A → config B, the category that regressed, the
  flipped cases, and the retrieval-vs-generation attribution — reproducible by a reader.

### Phase 13 — Docs, README, polish — *Milestone C*

- **Goal.** A repo a hiring manager can read in ten minutes and an engineer can run in one.
- **Main decisions.** README structure; how much of the decision log to surface up front;
  whether a visitor can run anything without their own API key.
- **Key risks.** Docs drifting from code; leftover scratch files; anything touching §0.
- **Done when.** The brief's definition of done is met and the repo passes a clean-checkout
  run-through.

---

## Why this order

1. **Nothing can be measured before there is something to measure against.** The corpus
   (2) fixes the document format, which fixes the pipeline's ingestion shape (4) and the
   test set's provenance (3). Choosing a stack (1) before the corpus is acceptable only
   because the stack decision is mostly corpus-independent; if the corpus turns out to
   demand heavy document parsing, Phase 1 gets revisited.
2. **The test set comes before the pipeline, in seed form.** It is the hard problem, and
   the brief is right that it must not become an afterthought. But writing it at full size
   before anything runs risks 150 cases against a wrong schema — hence the v0/v1 split
   (3 and 7) with the walking skeleton in between.
3. **Retrieval metrics (6) come before the judge (8).** Retrieval scoring is deterministic
   and needs no LLM, so it gives a complete, cheap, testable A/B signal at Milestone A —
   and it is the half of the system the judge cannot rescue. If retrieval attribution is
   wrong, every generation score built on it is misattributed.
4. **Calibration (9) immediately follows the judge (8).** An uncalibrated judge is not
   evidence. Leaving calibration to the end invites shipping numbers we cannot defend.
5. **Noise handling (11) comes last among the measurement phases**, because estimating
   run-to-run variance requires a working single-run path to repeat.

## Alternative orderings considered

- **Judge first, test set later.** Tempting because the judge feels like the interesting
  part. Rejected: the judge cannot be calibrated without labelled cases, so it would be
  built blind and rewritten once real cases arrive.
- **Full test set (7) before any code.** Maximises "test set is the hard problem"
  seriousness. Rejected: it front-loads the most expensive manual work against an
  unvalidated schema and category taxonomy, with no feedback from a running system.
- **Adapter for an external RAG system first, own pipeline later.** Rejected for now
  because there is no external system to point at yet; revisit if Aksh has one in mind,
  since it would reverse Phases 4 and 12.
- **Reports and UI early, metrics later.** Rejected: a report is a view over results that
  do not exist yet, and building it first tends to freeze a results schema chosen for
  display convenience rather than correctness.

---

## Open questions blocking the next phase

Tracked in full in the session notes; batch 1 is: repo home and stack constraints,
corpus choice, provider access and budget, and own-pipeline-versus-adapter scope.

### Phase 14 — Adapter for an external RAG system

- **Goal.** Point the harness at Aksh's own chatbot, through the boundary defined in
  D-004, without changing the harness.
- **Main decisions.** The adapter interface (already fixed in principle: questions in,
  answers plus retrieved sources out); how a system that cannot report its retrieved
  sources is handled; whether the adapter and any results are committed or kept local.
- **Key risks.** The interface turns out to be CUAD-shaped and does not fit real output;
  the external system cannot expose retrieved sources at all, which would make retrieval
  and generation impossible to score separately — the harness's main claim.
- **Done when.** One real evaluation run against an external system produces a report in
  the same format as a CUAD run.

# Failure map

The "if X breaks, go here" guide. For each component: what can fail, what that looks
like from the outside, where to look first, and how to recover.

This document is written from the symptom inwards, because that is the direction you
read it in when something is broken.

**Status:** covers the configuration and dataset layers. Entries are added
in the same step that builds the component they describe — a component is not "done"
until its failure modes are listed here.

---

## Quick index: symptom → section

| Symptom | Go to |
|---------|-------|
| An A/B comparison reports no difference between configurations you know differ | [Configuration — a setting that never took effect](#configuration--a-setting-that-never-took-effect) |
| A run fails immediately with `Invalid configuration ...` | [Configuration — rejected at load](#configuration--rejected-at-load) |
| Two runs you expect to match produce different fingerprints | [Hashing — fingerprint changed unexpectedly](#hashing--fingerprint-changed-unexpectedly) |
| Tests pass locally but fail in CI | [Tooling — CI has no credentials](#tooling--ci-has-no-credentials) |
| Scores moved and you did not change the configuration | [Dataset — documents changed underneath you](#dataset--documents-changed-underneath-you) |
| `ingest` stops saying the fingerprint does not match | [Dataset — the upstream archive changed](#dataset--the-upstream-archive-changed) |
| `ingest` stops naming contracts and categories | [Dataset — the source failed validation](#dataset--the-source-failed-validation) |

---

### Configuration — a setting that never took effect

- **What fails:** a field in the configuration file is spelled wrong, so the intended
  value is never read.
- **Symptom:** the worst kind. Two configurations that should differ produce identical
  results, and the comparison reports "no regression" with complete confidence. Nothing
  errors, nothing looks wrong.
- **Look first:** this should be impossible now. The configuration model refuses unknown
  fields, so `top_K: 5` fails at load with both problems named — the unknown field, and
  the real field now missing. If you ever see silent agreement between configurations
  that should differ, check that `extra="forbid"` is still set on `_Section` in
  `src/rag_eval/config.py`.
- **Fix / recover:** correct the spelling. Any run made before the fix is invalid and
  must be discarded, not reinterpreted.
- **Prevented or caught by:** `tests/test_config.py::test_unknown_field_is_rejected_and_named`.

### Configuration — rejected at load

- **What fails:** the file is missing, empty, not valid YAML, or a field is out of range.
- **Symptom:** the run stops immediately with `Invalid configuration <path>:` followed by
  one line per problem.
- **Look first:** the message itself. It names the file and the full path to every field
  at fault, and reports all problems at once rather than one per attempt.
- **Fix / recover:** nothing has run, so nothing is corrupted. Fix the file and rerun.
- **Prevented or caught by:** the load-time tests in `tests/test_config.py`.

### Hashing — fingerprint changed unexpectedly

- **What fails:** two configurations that should be equivalent produce different
  fingerprints, or two that differ produce the same one.
- **Symptom:** later, once caching exists, this appears as cache misses that should have
  been hits, or — far worse — as results from one configuration being served under
  another's name.
- **Look first:** `content_hash()` in `src/rag_eval/config.py`. It excludes `name` on
  purpose and includes everything else. If a field is added to the model and does affect
  answers, it is included automatically; if a field is added that does *not* affect
  answers, it must be excluded deliberately or it will cause spurious misses.
- **Fix / recover:** cheap for now. Once a cache exists, a fingerprint bug means the
  cache must be discarded, because there is no way to tell which entries are sound.
- **Prevented or caught by:** `tests/test_hashing.py`, which checks stability, key-order
  independence, that `name` is ignored, and that real settings change the fingerprint.

### Tooling — CI has no credentials

- **What fails:** code reads an API key when a module is imported, so it works on a
  machine with a `.env` file and fails everywhere else.
- **Symptom:** tests pass locally, fail in CI with a missing-key error.
- **Look first:** `tests/test_no_keys.py`, which imports the package in a subprocess with
  the environment stripped. It reproduces the CI failure locally in under a second.
- **Fix / recover:** move the key read out of module scope and into the call that needs
  it — which, once it exists, means the provider wrapper and nowhere else.
- **Prevented or caught by:** `tests/test_no_keys.py`, and the CI workflow having no
  secrets configured at all.

---

### Dataset — documents changed underneath you

- **What fails:** a contract file is edited, truncated or replaced after ingestion.
- **Symptom:** scores move between runs you expected to match, and the configuration
  change you happened to make takes the blame. Extremely hard to diagnose from the
  numbers alone, which is why it is checked rather than reasoned about.
- **Look first:** `uv run python -m rag_eval verify --dataset data/cuad/v1`. It re-hashes
  every contract file against the index and names each one that no longer matches.
- **Fix / recover:** re-run `ingest`. Any run made against the altered data is invalid
  and must be discarded — its recorded fingerprint will not match the fresh one, which
  is how you can tell which runs are affected.
- **Prevented or caught by:** `tests/test_dataset.py::test_loader_detects_a_contract_edited_after_ingestion`.

### Dataset — the upstream archive changed

- **What fails:** the published archive no longer matches the fingerprint recorded in
  `src/rag_eval/dataset/ingest.py`.
- **Symptom:** `ingest` stops before unpacking anything, printing the expected and the
  actual fingerprint.
- **Look first:** the two fingerprints in the message. A difference means the upstream
  file genuinely changed, not that anything local is broken.
- **Fix / recover:** decide deliberately. If the new upstream data is wanted, update the
  recorded fingerprints and bump the dataset version, because results from the old data
  are no longer comparable with results from the new. Never update the fingerprint
  simply to make the command pass.
- **Prevented or caught by:** `tests/test_dataset.py::test_source_fingerprint_mismatch_stops_ingestion`.

### Dataset — the source failed validation

- **What fails:** an answer offset does not point at the text it claims to, two
  contracts collapse to the same identifier, or a category in the labels has no
  description.
- **Symptom:** `ingest` stops and lists up to ten problems, each naming the contract and
  category involved.
- **Look first:** the message. The offset check is the important one — if answer
  positions drift, every retrieval score built on them is wrong while looking entirely
  reasonable.
- **Fix / recover:** nothing has been written, so nothing is corrupted. The fault is in
  the source data or in `cuad.py`, and it needs understanding rather than suppressing.
- **Prevented or caught by:** `test_a_wrong_offset_is_rejected_and_named`,
  `test_colliding_contract_identifiers_are_rejected`, and
  `test_a_category_used_but_not_described_is_rejected`. The last of these caught a real
  mismatch in the published corpus on its first run against real data.

---

## Entry template

```markdown
### <Component> — <failure mode>

- **What fails:** the specific thing that breaks.
- **Symptom:** what you actually see — the error text, the wrong number, the silence.
- **Look first:** the file, log query, or artefact that confirms or rules it out.
  (Log lines carry `run_id` and `case_id`; name the fields to filter on.)
- **Likely cause(s):** in order of probability.
- **Fix / recover:** the action, and whether the run is salvageable or must be redone.
- **Prevented or caught by:** the test, validation, or assertion that should have
  caught it — or "nothing yet", which is itself a finding.
```

---

## Cross-cutting failure modes to cover

These are the ones that cost the most when missed, listed here so they do not get
forgotten as components are built:

- Silent scoring on a partial run (errors excluded from the denominator).
- Cache returning a stale entry after a prompt or model change.
- Judge output that validates against the schema but cites context that does not exist.
- A config change that does not actually reach the pipeline (edited, but not read).
- A dataset edit that invalidates existing results without changing the dataset hash.

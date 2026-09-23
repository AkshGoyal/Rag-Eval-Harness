# Failure map

The "if X breaks, go here" guide. For each component: what can fail, what that looks
like from the outside, where to look first, and how to recover.

This document is written from the symptom inwards, because that is the direction you
read it in when something is broken.

**Status:** covers the configuration, dataset, test-set, retrieval and model-call layers. Entries are added
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
| On Windows, `verify` says every contract "has changed since ingestion" | [Dataset — line endings rewritten on disk](#dataset--line-endings-rewritten-on-disk) |
| `ingest` stops saying the fingerprint does not match | [Dataset — the upstream archive changed](#dataset--the-upstream-archive-changed) |
| `ingest` stops naming contracts and categories | [Dataset — the source failed validation](#dataset--the-source-failed-validation) |
| Every configuration scores the same on some category | [Test set — questions that answer themselves](#test-set--questions-that-answer-themselves) |
| `build-testset` stops saying a stratum is short | [Test set — a stratum cannot be filled](#test-set--a-stratum-cannot-be-filled) |
| A rebuilt test set no longer matches the committed one | [Test set — the set drifted](#test-set--the-set-drifted) |
| Every configuration scores near zero | [Retrieval — the question cannot reach its document](#retrieval--the-question-cannot-reach-its-document) |
| Two identical runs rank chunks differently | [Retrieval — unstable ranking](#retrieval--unstable-ranking) |
| Scores changed and no configuration did | [Model calls — the gateway switched provider](#model-calls--the-gateway-switched-provider) |
| A rerun returns old answers under a new model's name | [Model calls — a stale cache entry](#model-calls--a-stale-cache-entry) |
| A run stopped partway with a spending message | [Model calls — the budget cap tripped](#model-calls--the-budget-cap-tripped) |
| Answers end mid-sentence | [Model calls — truncated output](#model-calls--truncated-output) |
| A call is refused with "no price is known" | [Model calls — a model with no price](#model-calls--a-model-with-no-price) |
| Identical configurations give different answers weeks apart | [Model calls — an alias was re-pointed](#model-calls--an-alias-was-re-pointed) |

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

### Test set — questions that answer themselves

- **What fails:** a question contains its own answer, so the system succeeds without
  retrieving anything.
- **Symptom:** every configuration scores identically on that category, and an A/B
  comparison reports no difference where a real one exists. It looks like a stable
  result rather than a broken one.
- **Look first:** `answer_overlap` on the affected cases, and `max_answer_overlap` in
  `testset/seed-v1.manifest.json`. Anything approaching 0.5 deserves reading by eye.
- **Fix / recover:** reword the phrasing in `testset/templates.yaml` and rebuild, or let
  the threshold exclude the case. Both change the test set's fingerprint, so results
  from before the change are not comparable with results after.
- **Prevented or caught by:** the overlap check at build time, which currently rejects
  429 "Document Name" and 73 "Governing Law" cases. Not caught: a question answerable
  from general knowledge without retrieval. That needs the no-context baseline, which
  does not exist yet.

### Test set — a stratum cannot be filled

- **What fails:** a case type has fewer candidates than the build asks for, often
  because the contract-per-case cap has exhausted the eligible contracts.
- **Symptom:** `build-testset` stops with "wanted N, found M".
- **Look first:** the counts by type in the corpus against the requested strata.
- **Fix / recover:** lower the quota or raise the cap — deliberately. A category with
  too few cases cannot support a claim about that category, so silently accepting a
  short stratum would be worse than stopping.
- **Prevented or caught by:** `tests/test_testset.py::test_a_stratum_that_cannot_be_filled_is_reported`.

### Test set — the set drifted

- **What fails:** rebuilding produces different cases from the committed ones.
- **Symptom:** the fingerprint in the manifest changes without anyone intending it.
- **Look first:** which input moved — the corpus fingerprint, the phrasings' fingerprint,
  or the seed. All three are recorded in `testset/seed-v1.manifest.json`, so the
  comparison is immediate.
- **Fix / recover:** if the change was intended, commit the new set and treat earlier
  results as belonging to a different test set, because they do. If it was not intended,
  the corpus or the phrasings changed underneath you.
- **Prevented or caught by:** `test_building_is_reproducible` and
  `test_shipped_seed_set_is_intact`.

---

### Retrieval — the question cannot reach its document

- **What fails:** the question names its contract using words that do not appear in that
  contract, so nothing in the query can identify the right document.
- **Symptom:** recall near zero across every configuration. It looks like a broken
  retriever or a hopeless task; it is neither. This happened for real: names derived from
  filing identifiers squash the company into one token ("lejuholdingsltd") that exists
  nowhere in the corpus, and recall was 0 of 19.
- **Look first:** take one failing question, tokenise it, and check each word against the
  target contract's text. A distinctive word that appears in neither the corpus vocabulary
  nor the target document is the whole answer.
- **Fix / recover:** name contracts with text drawn from the documents themselves — the
  expert "Document Name" and "Parties" annotations are quotations from the contract. The
  test set has to be rebuilt, which changes its fingerprint, so earlier results are not
  comparable.
- **Prevented or caught by:** nothing automatic yet. It was caught by running retrieval
  end to end on real data at the first opportunity. A floor-effect check — refusing to
  report an A/B when every configuration scores zero — belongs in the metrics phase.

### Retrieval — unstable ranking

- **What fails:** two chunks score identically and the order between them varies, so a
  rerun of an unchanged configuration produces a different ranking.
- **Symptom:** small, inexplicable deltas between runs that should be identical, which
  would be read as noise or, worse, as a real regression.
- **Look first:** `BM25Index.search` breaks ties by document order through `np.lexsort`.
  If that is removed, ties fall back to whatever order the sort happens to produce.
- **Fix / recover:** restore the tie-break. Any A/B run made while it was absent is
  untrustworthy, because the variance has no bound you can state.
- **Prevented or caught by:** `tests/test_pipeline.py::test_ties_break_by_document_order`
  and `::test_retrieval_is_deterministic`.

---

### Model calls — the gateway switched provider

- **What fails:** OpenRouter routes the same model name to a different upstream
  provider between two runs. Providers differ in quantisation and behaviour.
- **Symptom:** scores move between runs whose configuration is identical, or an A/B
  delta that is really a provider difference wearing a configuration's clothes.
- **Look first:** `provider_served` on the call records for both runs. If they differ,
  the comparison is invalid regardless of what the scores say.
- **Fix / recover:** pin the provider in the request, which the wrapper does by setting
  `allow_fallbacks: false`. Runs made without pinning cannot be repaired after the fact,
  only repeated.
- **Prevented or caught by:** `tests/test_llm.py::test_the_serving_provider_is_recorded`
  and `::test_pinning_a_provider_disables_fallback`.

### Model calls — a stale cache entry

- **What fails:** something that changes a model's answer is not part of the cache key,
  so a previous answer is served for a new configuration.
- **Symptom:** none. This is the failure with no symptom — the answer is well-formed,
  the run completes, the report looks ordinary, and the number is false.
- **Look first:** whether the changed field appears in `ChatRequest` or
  `EmbeddingRequest`. The key is the whole request, so a field missing from the model is
  a field missing from the key. If in doubt, delete `.cache/` and rerun; a real
  difference will reappear.
- **Fix / recover:** add the field to the request model, then discard the cache
  entirely. Entries written under the old key cannot be told apart from sound ones.
- **Prevented or caught by:** the parametrised test asserting that model, prompt
  version, temperature, output limit, provider and message content each change the key.

### Model calls — the budget cap tripped

- **What fails:** the run reached its spending limit.
- **Symptom:** it stops with what was spent, the limit, and how many calls had been made.
- **Look first:** whether the spend is plausible for the work. If it is far higher than
  expected, suspect a loop rather than the prices.
- **Fix / recover:** results up to that point are complete and usable; anything after it
  was not attempted. Raise the limit deliberately or narrow the run — never remove the cap.
- **Prevented or caught by:** `tests/test_llm.py::test_the_run_stops_at_its_spending_limit`.

### Model calls — truncated output

- **What fails:** the model hit its output limit mid-answer.
- **Symptom:** answers ending mid-sentence, and judge scores that look unfairly harsh.
- **Look first:** `truncated` on the call record. It is set from the provider's finish
  reason, so a truncated answer is never scored as though the model chose to stop.
- **Fix / recover:** raise `max_output_tokens` in the configuration and rerun. That
  changes the cache key, so the affected calls are genuinely remade rather than reused.
- **Prevented or caught by:** `tests/test_llm.py::test_a_truncated_answer_is_recorded_as_truncated`.

---

### Dataset — line endings rewritten on disk

- **What fails:** a contract's text is written or read in text mode, and the operating
  system rewrites its line endings on the way.
- **Symptom:** on Windows, every contract fails verification immediately after a clean
  ingestion. The tamper check is working correctly; the writer changed the bytes. On any
  platform, a corpus containing carriage returns would come back subtly different, with
  every answer offset after the first affected line shifted.
- **Look first:** whether the file was written with `write_text` or opened in `"w"` mode.
  Contract text must be written as bytes, and read back from bytes, so that the bytes
  fingerprinted, written and read are the same bytes.
- **Fix / recover:** re-run `ingest` after the fix. Nothing downstream is affected,
  because the corpus fingerprint is computed from the in-memory text, not the file.
- **Prevented or caught by:** `tests/test_dataset.py::test_contract_text_survives_the_disk_byte_for_byte`,
  which catches the read side anywhere, and the Windows job in CI, which is the only
  thing that can catch the write side. Found on the first run on a Windows laptop.

---

### Model calls — a model with no price

- **What fails:** a configuration names a model the gateway's catalogue does not price
  and `configs/prices.yaml` does not list.
- **Symptom:** the call is refused before it is made, with a message naming the model.
  This is deliberate. The previous behaviour — counting the call as free — hid every
  embedding call from the spending limit and showed nothing.
- **Look first:** `uv run python -m rag_eval models --search <name>`. If the model is
  not listed, check the id for a typo. If it genuinely exists but is unpriced, read its
  price from the gateway's website.
- **Fix / recover:** add the model to `configs/prices.yaml` with its price, where the
  number came from, and the date you checked it.
- **Prevented or caught by:** `tests/test_llm.py::test_a_model_with_no_known_price_is_refused_before_any_call`
  and `::test_setup_check_prices_an_embedding_the_catalogue_omits`.

### Model calls — an alias was re-pointed

- **What fails:** the configuration names an alias such as
  `~deepseek/deepseek-v4-flash-latest`, and the gateway re-aims it at a newer model.
- **Symptom:** a rerun of an unchanged configuration produces different answers, and
  nothing in the configuration changed to explain it.
- **Look first:** whether any model id in the configuration starts with `~` or ends in
  `-latest`.
- **Fix / recover:** name a fixed model instead. Results produced under the alias
  cannot be attributed to a specific model after the fact.
- **Prevented or caught by:** nothing automatic yet. A configuration check rejecting
  alias ids belongs with the generator's configuration in the next phase.

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

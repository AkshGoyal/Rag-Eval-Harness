# Evaluation methodology

What every number in a report means, how it is computed, and — as importantly — what it
cannot tell us. A metric without a stated blind spot is a metric we will over-trust.

**Status:** empty. Sections are filled as each metric and each part of the test set is
built. No metric ships without its "what it can't detect" line.

---

## 1. Metrics

_TBD._ One entry per metric, using the template below.

```markdown
### <metric name>

- **What it measures:** in one sentence, in terms of the user-visible behaviour.
- **How it's computed:** the exact definition, including tie-breaks and edge cases
  (empty retrieval, refusal, error).
- **Range and direction:** what a good value looks like.
- **What it can't detect:** the failure it will score as a pass.
- **Known biases:** systematic skew, and in which direction.
- **Where it's implemented:** file and function.
```

### 1.1 Retrieval metrics

Scored separately from generation, so a failing case can be attributed to "retrieval
missed the source" or "the generator misused good context". No model is involved in
computing any of these. Implemented in `src/rag_eval/metrics/retrieval.py`.

A retrieved chunk **covers** a gold answer span when it comes from the right contract
and its character range overlaps the span at all. The same clause type in a different
contract does not count.

**hit@k** — share of cases where any chunk in the top k covers any gold span.
- *Can't detect:* whether enough of the answer was retrieved. A chunk holding the last
  three words of a clause counts as a hit.
- *Bias:* larger chunks overlap spans more easily, so hit@k rises with chunk size partly
  for reasons unrelated to search quality.

**span recall@k** — for each case, the share of its gold spans covered within the top k,
averaged over cases. Equal to hit@k for single-span answers.
- *What it adds:* for a multi-hop answer split across several places, finding one piece
  is a partial result, and hit@k would call it a full one.
- *Can't detect:* whether the pieces found are the ones that matter most.

**MRR** — mean of 1 / (rank of the first covering chunk), zero when none is found.
- *What it adds:* rewards putting the answer first, which matters because a generator
  reads the top passages most closely.
- *Can't detect:* anything below the first hit.

**What is never folded into these numbers.** Refusal cases have no passage to find; they
are counted and reported as "not scored", never silently removed. A case whose retrieval
failed is recorded with its reason and scores zero, so the average stays an average over
every case attempted.

### 1.2 Generation metrics

_TBD._

### 1.3 Cost and latency

_TBD._

---

## 2. Pass criteria

_TBD._ What makes a case a pass, and why that definition was chosen over the
alternatives (score threshold, binary verdict, conjunction of criteria).

---

## 3. The test set

- **Provenance:** the Contract Understanding Atticus Dataset (CUAD), licensed CC BY 4.0
  — 510 commercial contracts filed publicly with the SEC, annotated by legal experts.
  Ingested from the project's GitHub repository and fingerprinted; see D-003 and D-007.

  What the corpus gives us, before any test case is written:

  | | Count | What it is for |
  |---|---|---|
  | Contracts | 510 | The documents retrieval searches |
  | Question-and-contract pairs | 20,910 | The pool test cases are drawn from |
  | — with an answer, located exactly | 6,702 | Retrieval ground truth, free of charge |
  | — expert-confirmed absent | 14,208 | Cases where refusing is the correct answer |
  | Clause categories | 41 | The basis of the category taxonomy |

  Two properties matter more than the counts. Every one of the 13,823 answer spans was
  checked against its contract's text at ingestion, and all of them are correct, so the
  answer locations can be trusted as ground truth rather than sampled and hoped for.
  And the categories vary enormously in how often they appear — "Document Name" is in
  all 510 contracts, "Source Code Escrow" in 13 — which gives graded difficulty without
  anyone having to guess what is hard.
- **How cases were written:** from hand-written templates, two phrasings per clause
  category, frozen in `testset/templates.yaml` (D-008). Nothing generates a question at
  run time, so the same corpus, phrasings and seed always produce the same cases.
  Nothing that wrote a phrasing ever saw a contract or an answer.

  Reference answers were not written by anyone. For a clause that is present, the
  reference is the expert-annotated span text. For one confirmed absent, it is that the
  contract does not say so. Every assertion in the test set traces back to CUAD's
  annotations.

- **Category definitions:** five types, derived from the corpus rather than imposed on it.
  CUAD asks two shapes of question — what is the value, and is this kind of clause here
  at all — and each can be answerable or not.

  | Type | What the system must do | In the corpus |
  |---|---|---|
  | `extraction_single` | Pull one value from one place | 2,370 |
  | `extraction_multi` | Combine several places — the multi-hop case | 721 |
  | `existence_yes` | Confirm a clause is present, with evidence | 3,611 |
  | `existence_no` | State a clause is absent — the hallucination trap | 12,709 |
  | `not_stated` | Decline to give a value the contract lacks | 1,499 |

  A correction worth recording: multiple answer spans only mean multi-hop for extraction
  questions. For a yes/no question, one span is enough to answer, so those are not
  multi-hop however many spans they carry. Genuine multi-span extraction is 721 cases,
  508 of which are "Parties" — a contract names its parties in more than one place.
  Since seed-v2 (D-012) Parties and Document Name are never asked, because each
  contract's name is built from them. That leaves 213 multi-span extraction candidates.

- **Leakage checks:** each case records `answer_overlap`, the share of its reference
  answer's distinctive words that already appear in the question. Cases at or above 0.5
  are excluded at build time and counted in the manifest.

  Because questions come from templates whose only variable part is the contract's name,
  the wording cannot leak an answer. What can leak is the name itself. Measured over the
  whole corpus, the check rejects 429 of 510 "Document Name" cases — the question names
  the contract and the answer is the contract's name — and 73 "Governing Law" cases,
  where a company name contains a state or country. The second group was not predicted
  and is the reason the check is measured rather than argued.

  **What it cannot detect:** a question the generator can answer from general knowledge
  without retrieving anything. That needs an empirical no-context baseline, which is
  deferred to a later phase.
- **Category definitions:** _TBD_ — each category with its inclusion rule and a worked
  example, so that two people would classify a new case the same way.
- **Leakage checks:** _TBD_ — how we verify a question is not answerable from its own
  wording or from model parametric knowledge alone.
- **Size and per-category counts:** the seed set is 30 cases —
  8 existence_no, 6 existence_yes, 6 extraction_multi, 7 extraction_single, 3 not_stated — weighted for variety
  rather than to mirror the corpus, which is two-thirds absences. It is deliberately too
  small to support per-category claims; it exists to drive the walking skeleton and to
  expose design problems early. The full set is sized in Phase 7, once we know which
  categories actually distinguish one configuration from another.

  No case shares a contract with more than one other, so no single document can dominate
  a score through happening to chunk well.

  Reproducibility: the build records the corpus fingerprint, the phrasings' fingerprint
  and the seed. The committed set fingerprints to `28a811b4851e1785...`, and
  rebuilding from the same inputs reproduces it exactly.

---

## 4. Judge calibration

_TBD._ The judge is a model and can be wrong. This section records:

- the human-labelled sample used as ground truth, and how it was drawn;
- agreement between judge and human labels (raw agreement and a chance-corrected
  statistic), overall and per category;
- the cases where they disagree, and what the disagreements have in common;
- bias checks run: verbosity, position (in pairwise comparisons), and self-preference
  when judge and generator share a model;
- the citation-verification check: whether what the judge quotes actually exists in the
  retrieved context.

**Until the numbers in this section exist, judge scores are not evidence of anything.**

---

## 5. Noise and significance

_TBD._ How much a score moves between identical reruns, and the rule we use to decide
whether an A/B delta is bigger than that noise.

---

## 6. Known limitations

_TBD._ The honest list of what this harness does not measure.

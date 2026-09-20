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

_TBD._ Scored separately from generation, so that a failing case can be attributed to
"retrieval missed the source" or "generator misused good context".

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
- **How cases were written:** _TBD, Phase 3._ The known problem: CUAD's questions are
  annotation instructions, not questions. They read "Highlight the parts (if any) of
  this contract related to 'Governing Law' that should be reviewed by a lawyer." Feeding
  those to the harness would measure how well a RAG system follows labelling
  instructions, which is not the thing under test. Turning them into natural questions
  is the central task of Phase 3, and its main risk is writing questions that contain
  their own answers, which would flatter retrieval.
- **Category definitions:** _TBD_ — each category with its inclusion rule and a worked
  example, so that two people would classify a new case the same way.
- **Leakage checks:** _TBD_ — how we verify a question is not answerable from its own
  wording or from model parametric knowledge alone.
- **Size and per-category counts:** _TBD_ — with the reasoning for why each category has
  enough cases for a regression to be visible above noise.

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

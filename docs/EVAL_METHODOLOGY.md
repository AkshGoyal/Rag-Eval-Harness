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

- **Provenance:** _TBD_ — corpus, licence, and how cases were derived from it.
- **How cases were written:** _TBD_ — by hand, synthesised, or adapted from an existing
  benchmark, and who checked each reference answer.
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

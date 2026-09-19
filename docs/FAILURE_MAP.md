# Failure map

The "if X breaks, go here" guide. For each component: what can fail, what that looks
like from the outside, where to look first, and how to recover.

This document is written from the symptom inwards, because that is the direction you
read it in when something is broken.

**Status:** empty. Entries are added in the same step that builds the component they
describe — a component is not "done" until its failure modes are listed here.

---

## Quick index: symptom → section

| Symptom | Go to |
|---------|-------|
| _(none yet)_ | |

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

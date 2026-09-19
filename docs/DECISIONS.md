# Decision log

One entry per decision, newest last. Every technical choice belongs here — stack,
dataset, metric, data model, prompt design, file layout. If a choice was made and it
isn't in this file, that's a bug in our process.

**Status:** empty. No decisions made yet. Phase 0 (discovery) is in progress; the first
entries will be D-001 (repo home) onward once Phase 1 decisions are taken.

---

## Index

| ID | Decision | Phase | Date | Status |
|----|----------|-------|------|--------|
| _(none yet)_ | | | | |

Status values: `active`, `superseded by D-NNN`, `revisit — <trigger>`.

---

## Entry template

Copy this block for each new decision. Do not drop a field; if a field is genuinely
empty, write "none" and say why.

```markdown
## D-NNN — <short title>

- **Decision:** what we chose, stated concretely enough to act on.
- **Context:** the problem and the constraints in force at the time (budget, time,
  what already existed, what depended on this).
- **Alternatives considered:**
  - *<Option B>* — rejected because …
  - *<Option C>* — rejected because …
- **Why this one:** the deciding factors, in order of weight.
- **Risks / failure modes:** what can go wrong *because of this choice*.
- **How we'd detect it:** the symptom, and the specific log line, metric, or test that
  would surface it.
- **When to revisit:** the change in circumstances that would make us reconsider.
- **Date:** YYYY-MM-DD
```

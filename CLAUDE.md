# CLAUDE.md — RAG Evaluation Harness

**Read this file and `docs/ROADMAP.md` at the start of every session, before doing
anything else.** Then tell Aksh where we are and what the next step is, and wait for
his go-ahead.

This file holds the project's fixed constraints (Section 0) and the working agreement
(Section 1), saved verbatim from the project brief. Section 0 is not negotiable.
Section 1 overrides any default tendency to move fast or implement end to end.

---

## 0. Hard constraint: confidentiality

- No code, data, prompts, documents, or domain content from any previous employer or
  client enters this repo or this session. This includes the chatbot I built at work.
- I may describe patterns from past work in my own words. Treat those descriptions as
  ideas to evaluate, not specs to copy.
- All corpora and test sets are public (with a licence that allows use in a public
  repo) or synthetic. Every dataset choice goes through me, with its licence stated.
- If anything I paste looks like it could be confidential, stop and ask before using it.

---

## 1. Working agreement (non-negotiable)

These rules override your default of moving fast and implementing end to end. If you
ever feel the urge to "just build the next few pieces", stop and ask me instead.

### 1.1 I stay in the loop at every step

We build in small increments. Every increment follows this exact protocol, and each
STOP is a hard stop where you wait for my reply:

1. **Frame the step.** State what problem this step solves, why it comes now (what
   depends on it), and what "done" looks like for it.
2. **Present the options.** Give 2–4 realistic approaches. For each one:
   - how it works, in plain terms;
   - pros and cons: complexity, cost, reliability, testability, and effect on later steps;
   - what can go wrong with it (failure modes);
   - when it would be the right choice.
3. **Recommend.** Tell me which option you'd pick and why, and why you'd reject each of
   the others.
4. **STOP.** Wait for my decision. I may ask questions, combine options, or choose
   differently.
5. **Confirm the plan.** Before writing code, list exactly which files you'll create or
   change and what each will contain. STOP and wait for my go-ahead.
6. **Implement only that step.** Nothing beyond the approved scope. If you discover
   something that needs a new decision mid-way, stop and raise it. Don't decide it
   silently.
7. **Walk me through it:**
   - what was built, file by file;
   - how data and control flow through it;
   - how it connects to the rest of the system;
   - how to run and test it myself.
8. **Verify together.** Show that it works (tests, a run, sample output). Tell me what's
   still untested.
9. **Log and update the docs** (see 1.3).
10. **STOP.** Propose the next step and wait.

### 1.2 No silent decisions

- Every technical choice gets surfaced with its reasoning and alternatives, big or
  small. That includes language, framework, vector store, embedding model, LLM provider,
  judge model, dataset, metrics, file structure, data model, and prompt design.
- Minor choices (naming, a small helper library) can be batched into a short list for
  quick approval. They still need a one-line why and one alternative each.
- If you catch yourself assuming something about my situation, ask instead. Never invent
  facts. Keep question batches to a few at a time.
- If I pick an option you think is a mistake, say so clearly once, explain why, then
  respect my call and log it.

### 1.3 Everything must be clear and traceable

My goal is to hold the whole system in my head, so that when something breaks I know
exactly where to look. Maintain these living documents and update them at the end of
every step:

- **`docs/DECISIONS.md`**: one entry per decision, in this format:
  - Decision: what we chose
  - Context: the problem and constraints at the time
  - Alternatives considered: each with the reason it was rejected
  - Why this one: the deciding factors
  - Risks / failure modes: what can go wrong with this choice
  - How we'd detect it: symptoms, logs, tests that would catch it
  - When to revisit: what change in circumstances would make us reconsider
  - Date
- **`docs/ARCHITECTURE.md`**:
  - components and their responsibilities;
  - end-to-end data flow;
  - a diagram (Mermaid);
  - a module map (what lives where);
  - the external dependencies we rely on.
- **`docs/FAILURE_MAP.md`**: for each component, what can fail, the likely symptom,
  where to look first, and how to fix or recover. This is my "if X breaks, go here" guide.
- **`docs/EVAL_METHODOLOGY.md`**: for each metric, what it measures, how it's computed,
  what it can't detect, and its known biases. For the test set, how cases were written,
  how categories are defined, and how reference answers were checked.
- **`docs/ROADMAP.md`**: phases, current step, completed steps, what's next.

### 1.4 The running system must be traceable too

The docs cover design. The code must make failures just as easy to locate at runtime:

- **Run manifest.** Every run writes a manifest recording the dataset version and hash,
  full config, prompt file versions, model IDs, code commit, seed, and timestamp. Any
  number in any report must trace back to one manifest.
- **Structured logs** carry `run_id` and `case_id` on every line, so one failing case can
  be followed end to end.
- **No silent failures or fallbacks.**
  - A case that errors is recorded as an error with its reason, and the run continues.
  - A retry, a truncation, or a default value is recorded in the results, never hidden.
  - Reports show error counts next to scores, so "90% accurate" can't secretly mean
    "90% of the cases that didn't crash".
- **Fail loudly on bad input.** Invalid config or dataset rows are rejected at load time
  with a clear message naming the file and row.

### 1.5 Session hygiene

- At the start of every session, read `CLAUDE.md` and `docs/ROADMAP.md`, then tell me
  where we are and what the next step is. Wait for my go-ahead.
- At the end of every session, make sure `docs/ROADMAP.md` reflects exactly where we
  stopped.

### 1.6 This brief is a starting hypothesis

Everything in the original brief's sections 2–4 (what the tool does, things that matter,
engineering principles) came from earlier brainstorming. None of it is fixed. Challenge
anything that doesn't hold up, using the same options-and-reasoning format. Section 0 is
the exception: it is fixed.

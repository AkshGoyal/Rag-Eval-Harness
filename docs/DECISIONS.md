# Decision log

One entry per decision, newest last. Every technical choice belongs here — stack,
dataset, metric, data model, prompt design, file layout. If a choice was made and it
isn't in this file, that's a bug in our process.

---

## Index

| ID | Decision | Phase | Date | Status |
|----|----------|-------|------|--------|
| D-001 | Dedicated private repo, not the profile repo | 1 | 2026-09-19 | active — revisit at Phase 12 |
| D-002 | Commits authored as Aksh, Claude as co-author | 1 | 2026-09-19 | active |

Status values: `active`, `superseded by D-NNN`, `revisit — <trigger>`.

---

## D-001 — Project lives in its own private repo

- **Decision:** the harness lives in `AkshGoyal/Rag-Eval-Harness`, a dedicated
  repository, created private. It goes public when the Phase 12 worked example lands.
- **Context:** work began in `AkshGoyal/AkshGoyal`, which is the GitHub *profile README*
  repo — the page a visitor to the profile lands on. Six documentation files had been
  written into it before this was caught; they were removed and that repo restored to its
  original commit with nothing committed or pushed.
- **Alternatives considered:**
  - *Build in the profile repo* — rejected: that repo's artifact is a one-page README. A
    tool living inside it makes the profile harder to read and gives the project no
    linkable identity of its own.
  - *Public from day one* — rejected for now, not on principle. During a job search, a
    repo with three commits and empty docs is a weaker signal than no repo at all.
    Private→public is one click and preserves the whole commit history, so the "built in
    public" record is kept, just released later.
  - *Monorepo alongside other personal projects* — rejected: nothing is shared between
    them, and it would bury this project's README.
- **Why this one:** a clean, linkable URL for the portfolio; the profile stays readable;
  the decision to publish is deferred to the point where publishing helps.
- **Risks / failure modes:** (1) private means no outside eyes until Phase 12, so nothing
  external catches a bad assumption early; (2) the flip to public is easy to forget, and
  an unreleased portfolio piece has no value; (3) GitHub Actions minutes are metered on
  private repositories but free on public ones, so a CI-heavy Phase 1 could hit a quota
  that would not exist if the repo were public.
- **How we'd detect it:** (2) is a checklist item in Phase 12's done criteria; (3) surfaces
  as workflow runs failing with a billing/quota message rather than a test failure — if CI
  starts failing without a code change, check the Actions quota before debugging the code.
- **When to revisit:** at Phase 12, to flip to public. Sooner if CI quota bites, which
  would make flipping early the cheaper fix.
- **Date:** 2026-09-19

---

## D-002 — Commits authored as Aksh Goyal, with Claude as co-author

- **Decision:** commits are authored `Aksh Goyal <aksh.iitdelhi@gmail.com>` and carry a
  `Co-Authored-By: Claude` trailer. Set via repo-local git config.
- **Context:** the container's default git identity is `Claude <noreply@anthropic.com>`.
  Committing as-is would attribute every commit in a portfolio repository to Claude.
- **Alternatives considered:**
  - *Author as Claude* — rejected: the repository exists to show Aksh's engineering
    judgment, and the history is part of what a reader assesses. Claude-authored commits
    misrepresent whose decisions these are.
  - *Author as Aksh with no trailer* — rejected: inaccurate, and undisclosed AI
    involvement in a repo shown to employers is a credibility risk if inferred. The
    trailer is also a positive signal for an AI-engineering portfolio, not a liability.
- **Why this one:** it is simply what happened — the decisions are Aksh's, the typing is
  shared — and it stays accurate under scrutiny.
- **Risks / failure modes:** the config is repo-local, so a fresh clone or a new container
  silently reverts to the default identity and produces Claude-authored commits. This
  fails quietly; nothing blocks the commit.
- **How we'd detect it:** `git log --format='%an %ae' -5` at the start of a session, added
  to the session-start routine. A mis-authored commit already pushed needs a rebase to fix,
  so catching it before the first commit of a session matters.
- **When to revisit:** if the repo gains other contributors, or if authorship needs to be
  enforced by a hook rather than remembered.
- **Date:** 2026-09-19

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

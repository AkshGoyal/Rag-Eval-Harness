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
| D-003 | Corpus is CUAD (510 annotated contracts, CC BY 4.0) | 2 | 2026-09-19 | active |
| D-004 | Generic harness first, adapter for Aksh's chatbot second | 0 | 2026-09-19 | active |
| D-005 | Asymmetric cross-provider models: Gemini generator, OpenAI judge | 1 | 2026-09-19 | active |

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

## D-003 — The corpus is CUAD

- **Decision:** the reference corpus is the Contract Understanding Atticus Dataset —
  510 commercial contracts filed publicly with the SEC, annotated by legal experts with
  13,000+ labelled spans across 41 clause categories. Licence CC BY 4.0.
- **Context:** the harness needs a document set to be developed against. Two constraints
  dominated: (1) if the generator can answer from pretrained memory, retrieval quality
  stops affecting scores and the whole A/B premise collapses; (2) Aksh has 30–60 minutes
  total for manual labelling, so any corpus requiring hand-marked answer locations is out.
- **Alternatives considered:**
  - *SEC EDGAR filings (public domain)* — rejected for now: the best numeric corpus, but
    no annotations, so every answer location would be hand-marked, and HTML/XBRL parsing
    would consume the early phases. Retained as the natural expansion: CUAD's contracts
    came from EDGAR, so growing into it later is not a rewrite.
  - *PubMed Central Open Access* — rejected: licences are per-article and mixed
    (CC BY-ND sits in the same bundle), so the set needs filtering, and verifying
    biomedical reference answers is the heaviest reading load of the candidates.
  - *MultiHop-RAG (ODC-BY)* — rejected on two counts: its news corpus runs to Dec 2023
    and sits inside model training data, and it supplies the ready-made test set, which
    is the part of this project with the most to teach and the most to show.
  - *Wikipedia / HotpotQA* — rejected: the most memorised corpus in existence. Gold
    supporting-sentence labels do not compensate for a generator that already knows the
    answers.
- **Why this one:** the expert annotations *are* the retrieval labels, which converts a
  task Aksh has no time for into one already done. Beyond that: very low leakage, an
  unambiguous CC BY 4.0 licence, and documents long enough that chunking strategy has
  something to bite on.
- **Risks / failure modes:** (1) contract English is dense — if every config scores near
  zero, differences between configs vanish into a floor effect and the harness shows
  nothing; (2) the annotations are *spans*, not question-answer pairs, so converting them
  into natural questions is a design step with its own failure modes, chiefly questions
  that leak their own answers; (3) CUAD's 41 clause categories do not map onto the
  evaluation categories we care about (single-fact, multi-hop, numeric, refusal), so the
  taxonomy has to be built, not inherited.
- **How we'd detect it:** the seed test set at Phase 3 is the tripwire. If every config
  scores near 0% or near 100%, question difficulty is wrong and the corpus or the
  generation step needs revisiting — visible at Milestone A, before any expensive work.
- **When to revisit:** if the seed set shows a floor or ceiling effect; or if the adapter
  work makes a domain closer to Aksh's own system more useful.
- **Date:** 2026-09-19

---

## D-004 — Build the generic harness first, adapt to Aksh's chatbot second

- **Decision:** the harness is built and proven against its own reference RAG pipeline
  over CUAD. The boundary between harness and RAG system is defined up front — questions
  in, answers plus retrieved sources out — so that Aksh's own chatbot can be attached
  later through an adapter without reworking the harness.
- **Context:** three goals arrived together: evaluate Aksh's existing chatbot, understand
  how RAG evaluation works in general, and produce a portfolio piece. They pull in
  different directions only if the harness is coupled to whatever it measures.
  On confidentiality: Aksh has confirmed the chatbot material is not confidential and
  that §0 is not engaged by it. §0 remains in force as written for everything else, and
  nothing from that system is needed for the phases now planned.
- **Alternatives considered:**
  - *Adapter first, against the existing chatbot* — rejected: there would be nothing
    public to develop the harness against, no reproducible example a reader could run,
    and debugging the harness and the adapter simultaneously makes every failure
    ambiguous.
  - *Only ever evaluate the existing chatbot* — rejected: it would not be runnable by
    anyone else, which removes both the portfolio value and the general lesson.
- **Why this one:** one build serves all three goals. The reference pipeline doubles as a
  fixture that makes the harness testable without any external system, and the boundary
  discipline is what makes the adapter cheap when it comes.
- **Risks / failure modes:** the boundary gets shaped around CUAD's peculiarities and
  then does not fit a real chatbot's output; or the adapter is deferred indefinitely and
  the "evaluate my own system" goal quietly never happens.
- **How we'd detect it:** write the adapter interface *before* the CUAD pipeline
  implements it, and check it against what Aksh's chatbot can actually emit. If the
  interface needs CUAD-specific fields, the boundary is wrong.
- **When to revisit:** after Milestone A, when the interface has met real data.
- **Date:** 2026-09-19

---

## D-005 — Generator and judge come from different providers

- **Decision:** the reference pipeline uses **different model families for generation and
  judging**, both from the cheap tier:
  - **Generator:** Gemini Flash tier — free tier first (Google AI Studio, ~1,000–1,500
    requests/day), paid **Gemini 3.1 Flash-Lite** ($0.25/$1.50 per 1M) as overflow.
  - **Judge:** **GPT-4o-mini** ($0.15/$0.60 per 1M), on the OpenAI key Aksh already has.
  - **Embeddings:** OpenAI `text-embedding-3-small` ($0.02/1M) — ₹12 to index the entire
    corpus, and no third provider to integrate.

  Exact model IDs are verified against provider docs at Phase 4, not fixed here.

- **Context:** ₹1000 total for the project. Aksh's initial answer named GPT-4o and OpenAI
  embeddings, but that described his existing chatbot rather than a constraint here; he
  then confirmed any provider is acceptable. A survey of current pricing found a ~70×
  spread between the cheapest usable models and GPT-4o, which changes what is affordable
  rather than merely what is cheaper.

- **Alternatives considered:**
  - *GPT-4o for both* — rejected on arithmetic: ~₹520 per 100-case A/B, so the entire
    budget buys 1.9 runs including all development. Not a preference, a wall.
  - *One cheap model for both (e.g. GPT-4o-mini)* — rejected, though viable at ~₹31/run.
    A judge scoring answers from its own model family exhibits self-preference bias, and
    with cross-provider costing ~₹35/run there is no longer a price reason to accept it.
  - *Claude Haiku 4.5* — rejected on price for this role: at $1/$5 per 1M it is roughly
    10× the Gemini Flash-Lite tier and ~₹220 per A/B run.
  - *Cheapest available (Qwen3.7 Flash, Ling 3.0 Flash, ~$0.02–0.03/1M)* — rejected for
    the judge role specifically, and unverified. A judge must emit schema-valid JSON on
    essentially every call; a model that fails validation on a meaningful fraction of
    calls costs retries and contaminates results. Cheapest is a false economy here.
  - *Gemini 2.5 Flash-Lite ($0.10/$0.40)* — rejected despite being cheaper than 3.1:
    it is scheduled for retirement on 16 October 2026. Building on a model with weeks
    left is a self-inflicted migration.

- **Why this one:** splitting the providers makes self-preference bias *structurally
  impossible* rather than something to measure and correct — the judge cannot favour its
  own output because it never produced it. That property used to cost ₹305/run under a
  single-provider assumption; here it costs about ₹14. The asymmetry also matches what
  the two roles need: the generator should be cheap and not especially strong, because a
  powerful generator compensates for bad retrieval using prior knowledge and hides
  exactly the differences we are trying to measure, while the judge needs reliable
  instruction-following and valid structured output.

- **Risks / failure modes:** (1) two providers means two keys, two failure modes, two
  rate-limit regimes, and a provider wrapper that must genuinely abstract both;
  (2) Gemini's free tier runs at 5–15 requests/minute, so a 400-request run takes 30–80
  minutes — tolerable once, painful if the cache is not working; (3) free-tier inputs may
  be used for product improvement, acceptable for public CUAD text but not for anything
  else, and a constraint to re-check before the Phase 14 adapter sends any other corpus;
  (4) free-tier availability and quotas vary by region and change without notice;
  (5) cross-provider comparison assumes both models are competent at the task — if the
  Gemini generator is simply bad on legal prose, scores collapse to a floor and configs
  become indistinguishable.

- **How we'd detect it:** (2) and (4) surface as throughput collapse or 429s during a
  run, which the structured logs record per case rather than hiding in a retry;
  (5) is the same tripwire as D-003 — if the seed set scores near zero for every config,
  the generator, not the retrieval, is the problem. The cost model in this entry is
  checkable against the recorded spend in any run manifest; a large divergence means the
  token assumptions were wrong.

- **When to revisit:** if Gemini's free tier changes or is unavailable from India; if
  calibration (Phase 9) shows GPT-4o-mini disagreeing with Aksh's labels too often, in
  which case a stronger judge is paid for out of the reserve rather than assumed; or if
  the seed set shows a floor effect.

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

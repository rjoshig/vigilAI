# Phase Plan

Master overview. Each phase has its own detailed doc. Phases are **sequential** — do not
start phase N+1 until phase N's acceptance criteria are met (ask the user first if you think
you must). The phases and effort estimates come from [`design.md`](design.md) "Build
phases"; the order is deliberate: repo and a UI mock first so engineers can see the target,
then the pipeline as a CLI before the web app because LLM extraction quality is the biggest
risk.

| Phase | Title | Rough effort | Status | Doc |
| --- | --- | --- | --- | --- |
| 0 | Repo setup — structure, CLAUDE.md, docs, phase docs, standards, git rules, tooling | days | ✅ **complete** | [phase-0.md](phase-0.md) |
| 1 | UI mock — static `mock/` (user-ui, admin-ui, final report) | 1 week | ✅ **complete** | [phase-1.md](phase-1.md) |
| 2 | Pipeline core — CLI: files in, findings JSON out; parsers, rule schema, LLM adapter, cache, golden set on synthetic fixtures | 4–5 weeks | ✅ **complete** — real-model benchmark deferred (ADR-014) | [phase-2.md](phase-2.md) |
| 3 | Web app — docker-compose, new run, queue, history, review screen, stats, user-ui | 3 weeks | ✅ **complete** — `docker compose up` unverified (no Docker here) | [phase-3.md](phase-3.md) |
| 4 | Admin-ui and checks — templates, named values, checks, compliance rules, LLM-assisted authoring | 2–3 weeks | ✅ **complete** | [phase-4.md](phase-4.md) |
| 5 | Final report — one-page HTML in the compare-file format, freeze, PDF export | 1–2 weeks | ✅ **complete** | [phase-5.md](phase-5.md) |
| 6 | Hardening and in-house fit — PII masking, audit, retention, load test, adapt parsers to real samples | 2 weeks | 🟡 **in progress** — the rest needs real files and in-house infra | [phase-6.md](phase-6.md) |
| 6.1 | Richer inputs and a trainable rule loop — several samples per type, several files per report, type detection, and Train AI mode: reviewer observations synthesized into rules an administrator approves | 3–4 weeks | ✅ **complete** — two items open, listed in the doc | [phase-6.1.md](phase-6.1.md) |
| 6.2 | Optional login and attribution — two `.env` switches, admin-created accounts, sessions, and who-did-what on runs, reviews, and suggestions | 1–1.5 weeks | ✅ **complete** — login ships off; one item open | [phase-6.2.md](phase-6.2.md) |
| 6.3 | Runtime settings in the admin console — the console overrides `.env`, which overrides the defaults; model, login, throughput, uploads, retention | 1 week | ✅ **complete** | [phase-6.3.md](phase-6.3.md) |
| 6.4 | Showing the mode, and notes that follow a configuration — a Train AI indicator in both apps; standing notes on a configuration id that reach the model as background and the admin queue as comments | 1 week | ✅ **complete** — one test open | [phase-6.4.md](phase-6.4.md) |
| 6.5 | Training documentation, kept current — `user-training.md` and `admin-training.md`, re-read after every milestone and checked every ten commits | recurring | 🟡 **in progress** — by design, never closed | [phase-6.5.md](phase-6.5.md) |
| 6.6 | Themes — named themes shared by both apps, a picker that steps through them, and the default and lock set from the admin console | days | ✅ **complete** | [phase-6.6.md](phase-6.6.md) |
| 6.7 | Programme rules with a strictness, read by the model and graded by code, and a keyword check that a run is the programme it says it is | days | ✅ **complete** | [phase-6.7.md](phase-6.7.md) |
| 6.8 | Compliance and checks scoped to a programme; validation guides mapping a report cell to the OSL and the configuration with examples; the last ten versions of every definition, with revert | 2 weeks | ✅ **complete** | [phase-6.8.md](phase-6.8.md) |
| 6.9 | Delivery drift — new, resolved and carried-over findings, changed requirements, and the configuration diff against the previous finalized run of the same configuration | days | ✅ **complete** | [phase-6.9.md](phase-6.9.md) |
| 6.10 | Meaning — samples scoped per programme, a mapping interview that proposes requirement → config → report links for an administrator to confirm into shadow rules; edit and typed delete everywhere | 1–2 weeks | ✅ **complete** | [phase-6.10.md](phase-6.10.md) |
| 6.11 | Nothing slips — coverage of every requirement (checked, traced but unchecked, untraced, manual), a fail-closed finalize gate with an attestation, decision reasons and the bulk-OK fix, three independent lenses at stage 8 merged by code, a benchmark harness with precision and recall per finding type | 2–3 weeks | ✅ **complete** — the lens default stays `single` until a real model decides it | [phase-6.11.md](phase-6.11.md) |
| 6.12 | One front door — an administrator writes what they want checked in their own words and the model drafts it onto the surface that already runs it; one scope vocabulary in the API, both consoles and the documents | 1–2 weeks | ✅ **complete** | [phase-6.12.md](phase-6.12.md) |
| 6.13 | The loop closes — fifteen silent defects repaired (lens settings dropped by the worker, multi-part uploads overwriting each other, shadow compliance rules never running, and more), the observation author sees what became of it, findings carry their origin, judgment checks finished under ADR-001, an admin-curated and promoted example library for the model, a replay that evaluates | 3–4 weeks | ✅ **complete** | [phase-6.13.md](phase-6.13.md) |
| 6.14 | The artifacts belong together — an artifact match check that compares the submitted configuration id, customer and credit date against what the artifacts declare, before any model call, and holds the run until a person accepts each mismatch with a reason; the credit date resolved by scoped label and compared by value; one register and one marker for every field that reaches the model; tooltips on by default; the theme locked by default | 2–3 weeks | 🟡 **all but the live cap countdown**, carried into 6.17b | [phase-6.14.md](phase-6.14.md) |
| 6.15 | A compliance rule should survive being spelled differently — option C built: four deterministic tests widen the match so a different spelling and an extra level of nesting no longer produce false high-severity findings, with administrator-written alternates for the rest. Option A, the model as a locator, is built too | days | ✅ **complete** | [phase-6.15.md](phase-6.15.md) |
| 6.16 | Numbers that mean something — the delivery programme and a thirty-day count on the runs screen; which engine produced each finding; a dated report of orders validated and manual hours displaced, stating the assumption it rests on; and named-value labels that survive being spelled differently | days | ✅ **complete** | [phase-6.16.md](phase-6.16.md) |
| 6.17 | What is left, gathered in one place — the programme keyword check is the one surface never measured for the brittleness two others were; plus the deferred cap countdown, how scope reaches the compliance locator, and the rollout plan and training documents that have fallen behind | days | 🟡 **in progress** — 6.17a measured: brittle, and it fails at HIGH | [phase-6.17.md](phase-6.17.md) |
| 6.18 | Trust that is earned, measured, and revocable — findings that learn their own severity from the verdicts people actually gave, a maturity level an administrator sets deliberately, trustworthiness stated as a dated number, nothing hidden without a record, and a random sample reviewed in full forever so drift is caught by the tool rather than by the customer | weeks | ⬜ **not started** | [phase-6.18.md](phase-6.18.md) |
| 6.19 | Say what helps, and teach it in the product — a marker on every field that reaches the model or decides what it is shown, and a Guide in each app's sidebar written for the person in front of it | days | 🟡 **part A complete** — every field now says what it does; the in-app Guide is not started | [phase-6.19.md](phase-6.19.md) |
| 7 | Real-world fit — ingest the real OSL, config, and reports; adapt the parsers, prompts, and reference data; correct the docs | on demand | ⬜ **dormant** — runs only when the user asks, on the machine holding the real files | [phase-7.md](phase-7.md) |

Effort assumes 1–2 developers and is a starting estimate. Phase 6.1 is **not** part of
the original six either; it was added when it became clear that real campaigns bring
several files per report type and that the people reviewing findings are the ones who
know what else should be checked (ADR-021). It is numbered 6.1 rather than 8 because it
extends the configurable-checks work of Phase 4 rather than following Phase 7, and it
does not block Phase 6. Phase 7 is **not** part of the original six from `design.md`; it was added when it became clear the real files
would arrive on a different machine, and it is dormant until the user asks for it
(ADR-019).

Phase 6.11 came out of a product review on 2026-09-20 (`session-log.md`): the larger
risk was not the model but the review gate, which read the absence of a finding as a
pass. **Phase 6.12**, one front door for the admin console and one scope vocabulary, came
out of the same review and is specified in `phase-6.12.md`. **Phase 6.13** came out of a second
review (2026-09-20, `session-log.md`) that traced the whole flow and the learning loop
in code and found fifteen silent defects and an unclosed loop; it is specified in
`phase-6.13.md`.

The delivery itself, from readiness through UAT to region-by-region rollout, is
planned in [`gd-rollout-plan.md`](gd-rollout-plan.md), which is revisited at every milestone
here.

## Status vocabulary

⬜ `not started` → 🟡 `in progress` → ✅ `complete` · `superseded` / `dropped` with an ADR
reference.

**Every level carries a status**, and each one is derived from the boxes beneath it:

- the phase, on its status line and in the table above;
- each milestone (`### 2a — …`) and each scope group (`**Data + queue**`), stamped
  `· ✅ complete`, `· 🟡 in progress`, or `· ⬜ not started`;
- each individual item, as `- [x]` done, `- [ ]` not done, or `- [~]` partly met.

The three upper levels are **derived**, not typed: run
`python scripts/update_phase_status.py` after ticking boxes, and `scripts/check_docs.sh`
fails if they drift.

A phase is **complete** only when every box in its phase doc is ticked and the date is
on its status line.

A criterion that is deliberately left open stays unticked (or `- [~]` when partly met),
is labelled **outstanding** or **deferred** with the ADR that allows it, and is repeated
in the "Resume here" block of [`session-log.md`](session-log.md). This table and the
phase docs are updated in the same commit as the work they describe.

## Open questions carried from the design doc

These are unresolved product questions; each is a `# SPEC GAP:` until answered. Record the
answer as an ADR when it lands.

- [ ] One sanitized set (OSL, config JSON, DIRT and other reports) for the real layouts (needed by Phase 6; Phase 2 uses synthetic fixtures).
- [ ] Which in-house model and serving stack (vLLM, TGI, other)? JSON-schema guided decoding? Context length?
- [ ] Is there an attribute data dictionary to seed the alias table?
- [ ] Should users see only their own runs, or everyone's? (v1 has no login: everyone's.)
- [ ] Is 90-day storage of DIRT files containing PII approved?
- [x] Comparison against the same customer's previous run (drift)? **Yes**, built as
      Phase 6.9 (ADR-030): against the previous finalized run of the same configuration.
- [x] Phase 6.1's and 6.2's design questions — all answered 2026-09-18 and recorded in
      the "Decisions" table of each phase doc; ADR-021 and ADR-022 are accepted.
      Learned rules never expire on their own: they live in a searchable admin screen
      and an administrator enables, disables, or deletes them, with deletion
      restorable for six months.
- [ ] Are the fixed compliance rules maintained in the admin-ui or sourced elsewhere?
- [x] Must every high-severity finding have a decision before the final report can be generated? **Yes** (ADR-015).
- [ ] Do in-house configs name waterfall steps differently from the OSL (for example
      `suppress` against `exclusions`)? If so the step names need the alias table too.
      Raised by ADR-016; confirm against real files in Phase 6.
- [ ] Which model and endpoint should the golden set be benchmarked against? Phase 2
      acceptance criterion 2 is open until this is answered (ADR-014). A first hosted
      model passes the synthetic set (ADR-028); the in-house gateway on real files is
      the answer that matters, on the target environment.
- [ ] Confirm "last modified" means a timestamp inside the config JSON, not the upload time.

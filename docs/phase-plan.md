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
| 6.4 | Showing the mode, and notes that follow a configuration — a Train AI indicator in both apps; standing notes on a configuration id that reach the model as background and the admin queue as comments | 1 week | ⬜ **not started** — specified and decided; next to build | [phase-6.4.md](phase-6.4.md) |
| 7 | Real-world fit — ingest the real OSL, config, and reports; adapt the parsers, prompts, and reference data; correct the docs | on demand | ⬜ **dormant** — runs only when the user asks, on the machine holding the real files | [phase-7.md](phase-7.md) |

Effort assumes 1–2 developers and is a starting estimate. Phase 6.1 is **not** part of
the original six either; it was added when it became clear that real campaigns bring
several files per report type and that the people reviewing findings are the ones who
know what else should be checked (ADR-021). It is numbered 6.1 rather than 8 because it
extends the configurable-checks work of Phase 4 rather than following Phase 7, and it
does not block Phase 6. Phase 7 is **not** part of the original six from `design.md`; it was added when it became clear the real files
would arrive on a different machine, and it is dormant until the user asks for it
(ADR-019).

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
- [ ] Comparison against the same customer's previous run (drift)? Cheap once history exists.
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
      acceptance criterion 2 is open until this is answered (ADR-014).
- [ ] Confirm "last modified" means a timestamp inside the config JSON, not the upload time.

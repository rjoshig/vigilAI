# Phase Plan

Master overview. Each phase has its own detailed doc. Phases are **sequential** — do not
start phase N+1 until phase N's acceptance criteria are met (ask the user first if you think
you must). The phases and effort estimates come from [`design.md`](design.md) "Build
phases"; the order is deliberate: repo and a UI mock first so engineers can see the target,
then the pipeline as a CLI before the web app because LLM extraction quality is the biggest
risk.

| Phase | Title | Rough effort | Status | Doc |
| --- | --- | --- | --- | --- |
| 0 | Repo setup — structure, CLAUDE.md, docs, phase docs, standards, git rules, tooling | days | **in progress** | [phase-0.md](phase-0.md) |
| 1 | UI mock — static `mock/` (user-ui, admin-ui, final report) | 1 week | built, walkthrough pending | [phase-1.md](phase-1.md) |
| 2 | Pipeline core — CLI: files in, findings JSON out; parsers, rule schema, LLM adapter, cache, golden set on synthetic fixtures | 4–5 weeks | planned | [phase-2.md](phase-2.md) |
| 3 | Web app — docker-compose, new run, queue, history, review screen, stats, user-ui | 3 weeks | planned | [phase-3.md](phase-3.md) |
| 4 | Admin-ui and checks — templates, named values, checks, compliance rules, LLM-assisted authoring | 2–3 weeks | planned | [phase-4.md](phase-4.md) |
| 5 | Final report — one-page HTML in the compare-file format, freeze, PDF export | 1–2 weeks | planned | [phase-5.md](phase-5.md) |
| 6 | Hardening and in-house fit — PII masking, audit, retention, load test, adapt parsers to real samples | 2 weeks | planned | [phase-6.md](phase-6.md) |

Effort assumes 1–2 developers and is a starting estimate.

## Status vocabulary

`planned` → `in progress` → `complete` (acceptance criteria met, recorded in the phase doc
with the date) · `superseded` / `dropped` with an ADR reference.

## Open questions carried from the design doc

These are unresolved product questions; each is a `# SPEC GAP:` until answered. Record the
answer as an ADR when it lands.

- [ ] One sanitized set (OSL, config JSON, DIRT and other reports) for the real layouts (needed by Phase 6; Phase 2 uses synthetic fixtures).
- [ ] Which in-house model and serving stack (vLLM, TGI, other)? JSON-schema guided decoding? Context length?
- [ ] Is there an attribute data dictionary to seed the alias table?
- [ ] Should users see only their own runs, or everyone's? (v1 has no login: everyone's.)
- [ ] Is 90-day storage of DIRT files containing PII approved?
- [ ] Comparison against the same customer's previous run (drift)? Cheap once history exists.
- [ ] Are the fixed compliance rules maintained in the admin-ui or sourced elsewhere?
- [ ] Must every high-severity finding have a decision before the final report can be generated? (Proposed gate: yes.)
- [ ] Confirm "last modified" means a timestamp inside the config JSON, not the upload time.

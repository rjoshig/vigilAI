# Phase 6 — Hardening and in-house fit

**Status:** 🟡 **in progress** — everything that can be done from a development
checkout is done. What remains needs the real files, the in-house model, and the
platform and compliance teams, and is marked **in-house** below.

**Goal:** production readiness on the internal network and adaptation
of the parsers to the real file layouts, which are only available in-house. Effort ~2
weeks. Depends on Phases 3–5.

## Scope · 🟡 in progress

**Privacy and security** (`llm-privacy.md`, `design.md` "Security and PII") · 🟡 in progress
- [~] A PII regex tripwire runs on every assembled prompt, inside the adapter and
      before the cache, and **fails closed** (ADR-018). **in-house:** the masked-column
      list still has to be populated from the real DIRT layout; the shipped defaults
      cover the obvious columns and are a starting point, not an answer.
- [x] `audit_log` complete: run created, completed, failed, duplicate blocked,
      requirements edited, re-checked, finding reviewed, bulk-OK, finalized, report
      viewed, PDF downloaded, and every admin change. Asserted by a test.
- [x] Log review: a test drives a whole run and asserts no sample row reaches any log
      line. `LLM_LOG_PROMPTS` is false by default and the adapter warns on every call
      while it is on.
- [x] Upload hardening: extension and content-type checked together, a 50 MB limit
      enforced while streaming, directory components stripped from the filename, and a
      rejected upload leaves no partial file behind. Workbooks are read values-only, so
      macros are never evaluated.
- [ ] **in-house** TLS at the reverse proxy; encrypted volumes — with the platform
      team. On the checklist in `deployment.md`.

**Retention** · 🟡 in progress
- [x] The worker schedules its own retention sweep every 24 hours, so no cron entry
      is needed. `scripts/purge.py --dry-run` reports what would go; aggregated usage
      survives because `llm_calls` rows are kept with their run reference cleared.
- [ ] **Needs the user.** A decision on a shorter window for DIRT files, recorded as
      an ADR (open question in `phase-plan.md`).

**In-house fit** · 🟡 in progress
- [ ] **in-house** Adapt the parser implementations to the real layouts, on a machine
      that never pushes real files. The Protocols (ADR-006) exist so this is the only
      change needed; add a synthetic fixture mirroring each real layout's *shape*.
- [ ] **in-house** Point the adapter at the model gateway, enable guided JSON decoding
      if the serving stack supports it, and run
      `python scripts/golden_set.py --provider openai --out docs/benchmarks/phase-2.md`.
      This also closes Phase 2 criterion 2 (ADR-014). A first hosted model already
      scores 12 / 12 on the synthetic set (ADR-028); the in-house run is the one that
      counts, and it waits for the target environment.
- [~] The alias table is editable in the admin-ui and `scripts/seed_demo.py` shows the
      mechanism. **Needs the user:** whether a data dictionary exists to seed it from.

**Scale** · 🟡 in progress
- [~] `scripts/load_test.py` runs many submissions through the real API and several
      workers. It found a real race — two workers caching the same OSL section both
      inserted the same key and one run failed — now fixed and covered by a regression
      test. **in-house:** the ~80-user test, because the real cost is the model and the
      stand-in here is scripted.
- [x] Per-order-number queue cap verified, including under concurrent submission.

## Acceptance criteria · 🟡 in progress

1. [ ] **in-house** A real OSL / config / report set runs end to end with the pipeline unchanged
   except parser implementations and prompt examples.
2. [ ] **in-house** Golden-set accuracy on the in-house model recorded in
   `docs/benchmarks/`.
3. [ ] **Needs the user.** Security and compliance sign-off on retention and PII
   handling, recorded as an ADR.
4. [~] A local load test runs and its findings are fixed; the deployment checklist in
   `deployment.md` is written, with the **in-house** items still to tick.

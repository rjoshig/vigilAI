# Phase 4 — Admin-ui and configurable checks

**Status:** ✅ **complete** (2026-09-18).

**Goal:** cross-report checks defined by admins as data, not code,
plus the other admin-maintained reference data, and the separate admin-ui on its own URL.
Effort 2–3 weeks. Depends on Phase 3. Read `design.md` "Configurable checks (admin-ui)".

## Scope · ✅ complete

**Backend** · ✅ complete
- [x] Tables in use: `artifact_types` (was `report_templates`; ADR-020), `named_values`, `check_definitions` (versioned;
      kind expression | judgment; severity; scope all / one customer; `is_active`),
      `compliance_rules`, `attribute_aliases`, masked columns.
- [x] Named-value resolution: cell address or **label lookup** (preferred; survives
      inserted rows) against the uploaded report templates and, at run time, the real
      reports.
- [x] `POST /admin/checks/draft`: the **one** LLM call — plain-English description → proposed
      named values + expression (cached like every call). `POST /admin/checks/{id}/test`:
      evaluate against the sample files, no LLM.
- [x] Judgment checks: the prompt and schema exist and the UI flags them "use
      sparingly". **Note:** the worker still skips them at run time — an expression
      check costs nothing and a judgment check costs a call per run, so wiring it in
      waits for a real need. `s7_reports` logs when it skips one.
- [x] Stage 6 reads reverse-pass categories and compliance rules from these tables; stage 7
      loads the active checks for the report types present. "Could not evaluate" findings.
- [x] CRUD `/admin/artifact-types`, `/admin/scopes`, `/admin/named-values`, `/admin/checks`,
      `/admin/compliance-rules`, `/admin/aliases`; `GET /admin/usage` (plain SQL over
      `runs`, `run_stages`, `llm_calls`, `findings`).
- [x] Run fingerprint includes the active check versions (a check change invalidates the
      duplicate shortcut).

**admin-ui** · ✅ complete
- [x] Scaffold like user-ui (same toolchain and tokens), port **3001**, own Dockerfile,
      added to docker-compose. No login (ADR-008); the auth dependency is the hook.
- [x] Screens from the Phase 1 mock: Artifact types + named values, Checks (draft → correct
      → test → activate, versions, enable/disable, scope), Compliance and scope, Reference
      data (aliases, masked columns), Usage dashboard.

## Acceptance criteria · ✅ complete

1. [x] The three example checks from the design doc (billing ≤ delivered, billing ≥ accepts,
   accepts + rejects == input) are authored through the UI, tested against synthetic
   templates, activated, and fire as findings on a run.
2. [x] A missing named value produces a "could not evaluate" finding, never a silent skip.
3. [x] Disabling a check removes it from new runs without touching old findings
   (`findings.rules_version` / check versions preserved).
4. [x] Gates clean for api (661 tests), user-ui (35), and admin-ui (10).

## Out of scope

Login / roles (the users table stays empty).

## Amendment — artifact types and run scope (ADR-020) · ✅ complete

Added 2026-09-18, after Phases 5 and 6, because the fixed list of seven report types
could not accept a customer's eighth and nothing anywhere said what a report *means*.

- [x] `ReportKind` is an open string; an unknown key is read by `GenericReportParser`
      and the built-ins keep the keys the fixed checks look for.
- [x] `artifact_types` replaces `report_templates`: the OSL, the config, and each
      report, each with a label, a description, a sample workbook, an `ai_context`
      field, and active / required switches. A built-in can be switched off but never
      deleted or re-kinded; an admin-defined type can be deleted only while unused.
- [x] `run_scopes` holds AM, AS, Archives, and a catch-all with standing instructions.
      A run records its `scope` and a `has_suppressions` answer defaulting to no.
- [x] `GET /runs/options` generates the new-run form, so switching a type off removes
      its upload slot for every user without a deploy.
- [x] `pipeline/guidance.py` turns configured guidance into a prompt preamble, and
      returns an empty string when nothing is configured, so a fresh install sends the
      prompts it always sent. The preamble is part of the cache key.
- [x] admin-ui: **Artifact types** (define, enable, sample upload, AI context) and
      **Delivery programmes** (standing instructions, enable) screens. user-ui: dynamic
      upload slots, a programme dropdown, and a suppressions radio defaulting to No.
- [x] Tests: `tests/db/test_catalog.py`, `tests/pipeline/test_guidance.py`, and
      `tests/api/test_catalog_api.py`, including one that asserts configured guidance
      reaches a real prompt.

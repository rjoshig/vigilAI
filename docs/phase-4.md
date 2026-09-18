# Phase 4 — Admin-ui and configurable checks

**Status:** ✅ **complete** (2026-09-18).

**Goal:** cross-report checks defined by admins as data, not code,
plus the other admin-maintained reference data, and the separate admin-ui on its own URL.
Effort 2–3 weeks. Depends on Phase 3. Read `design.md` "Configurable checks (admin-ui)".

## Scope · ✅ complete

**Backend** · ✅ complete
- [x] Tables in use: `report_templates`, `named_values`, `check_definitions` (versioned;
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
- [x] CRUD `/admin/templates`, `/admin/named-values`, `/admin/checks`,
      `/admin/compliance-rules`, `/admin/aliases`; `GET /admin/usage` (plain SQL over
      `runs`, `run_stages`, `llm_calls`, `findings`).
- [x] Run fingerprint includes the active check versions (a check change invalidates the
      duplicate shortcut).

**admin-ui** · ✅ complete
- [x] Scaffold like user-ui (same toolchain and tokens), port **3001**, own Dockerfile,
      added to docker-compose. No login (ADR-008); the auth dependency is the hook.
- [x] Screens from the Phase 1 mock: Report templates + named values, Checks (draft → correct
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

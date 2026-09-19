# Phase 1 — UI mock

**Status:** ✅ **complete** (walkthrough signed off 2026-09-18). **Goal:** a static, clickable `mock/` showing every screen of
user-ui, admin-ui, and the final report, so engineers and stakeholders see the target
before anything is built. Same approach as `compare-file/ui-mock/`: plain HTML + one shared
`styles.css` + one shared `app.js`, opens from `file://`, no build, no backend. Effort ~1 week.

**Layout (ADR-013):** `mock/index.html` launcher · `mock/shared/` (styles, app.js) ·
`mock/user-ui/` · `mock/admin-ui/` — the two apps are separate directories, each with its
own `nav.js`, so they can be reviewed independently.

## Scope · ✅ complete

**Shared** · ✅ complete
- [x] `mock/shared/styles.css` — tokens copied from `compare-file/ui2` (`--primary`, `--card`,
      `--success`, … light + dark) so the mock and the apps match.
- [x] `mock/shared/app.js` — sidebar renderer, inline SVG icons, light/dark toggle, toast, and
      **synthetic** demo data only (invented customer names, states, thresholds).
- [x] `mock/README.md` — page list and re-skinning notes.

**user-ui pages** (`mock/user-ui/`, `design.md` "UI and report") · ✅ complete
- [x] `index.html` — Runs: history with filters, status badge (queued / running /
      needs review / finalized / failed), queue position, live stage progress.
- [x] `new-run.html` — form: customer name, order number, configuration ID, date, notes;
      drag-and-drop for OSL, config JSON, reports; "copy from previous run"; the
      duplicate-inputs dialog that shows the existing report and asks for a rerun reason.
- [x] `review.html` — the **traceability matrix** (one row per requirement; OSL / config /
      reports columns; match / mismatch / partial / missing / extra), findings list with
      severity + type filters, side panel with evidence (OSL text, config path + value,
      report cell, masked sample rows), OK / Not OK + comment per finding, bulk-OK for low
      severity, edit requirement / edit link + Re-check, waterfall view with breaks in red,
      attribute explorer, and the Generate final report button (disabled until every
      high-severity finding has a decision).
- [x] `report.html` — the frozen one-page report: header (customer, order, configuration
      ID, credit date, model, severity counts), AI summary, Not OK items with comments,
      expandable detail, Download PDF, Clone run.
- [x] `run-stats.html` — stage timings, LLM calls, tokens, cache hits.
- [x] `config-history.html` — captured configs by configuration ID and version with
      created / last-modified dates; copy into a new run. Same layout as the compare-file
      ui2 config screen.

**admin-ui pages** (`mock/admin-ui/`, own nav; entry `admin-ui/index.html`) · ✅ complete
- [x] Report templates — upload a sample Excel per report type; define named values
      (cell or label lookup) with descriptions.
- [x] Checks — create (plain-English description → proposed named values + expression),
      test against sample files, version, enable / disable, scope (all customers / one);
      judgment checks flagged "use sparingly".
- [x] Compliance and scope — must-have compliance rules; reverse-pass categories.
- [x] Reference data — attribute aliases; masked columns.
- [x] Usage — runs per day, p50/p95 duration, failure rate, tokens per day, cache hit
      rate, JSON-validation failure rate, false-positive rate.

## Acceptance criteria · ✅ complete

1. [x] Every page above opens from `file://` with no console errors and works in light and
   dark mode.
2. [x] Nav between pages works; every button shows a toast or navigates.
3. [x] No real customer data anywhere in the mock (reviewed in the PR).
4. [x] Stakeholder walkthrough done; feedback captured in `docs/session-log.md` and, where it
   changes the design, in `design.md` + an ADR.

## Out of scope

Pixel-perfect polish; any wiring to an API; any React.

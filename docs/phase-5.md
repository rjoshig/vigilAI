# Phase 5 — Final report

**Status:** planned. **Goal:** the frozen one-page interactive HTML report in the
compare-file report format, generated after review, with PDF download. Effort 1–2 weeks.
Depends on Phase 3 (Phase 4 for admin-check findings to appear). Read `design.md` "Review
and final report" and "UI and report".

## Scope

- [ ] `report/templates/`: Jinja2 one-page self-contained HTML (inline CSS/JS, opens
      offline) with the compare-file report look: brand topbar, header (customer, order,
      configuration ID, run date, model used, severity counts), AI summary + top issues,
      verdict and counts, the **Not OK items with comments**, expandable detail (evidence:
      OSL text, config path + value, report cell, masked sample rows), waterfall view,
      traceability matrix, attribute explorer. Light/dark.
- [ ] `POST /runs/{id}/finalize`: gate (proposed: every high-severity finding has a
      decision — confirm, open question), render **once**, store HTML on the volume, write
      `final_reports`, set `finalized`. A second call returns 409. **Never regenerated**
      (ADR-005).
- [ ] `GET /runs/{id}/report` serves the stored HTML; `GET /runs/{id}/report.pdf` renders
      the stored HTML in headless Chromium (Playwright in the worker image) with a print
      stylesheet that expands all findings, stores the PDF, serves it thereafter.
- [ ] user-ui Final report screen: view, Download PDF, Clone run.
- [ ] Masked values everywhere (app, HTML, PDF); no unmask control in v1.

## Acceptance criteria

1. Finalizing a reviewed synthetic run produces an HTML file that opens from `file://`
   with no network and matches the mock's layout.
2. The stored HTML never changes after finalize (hash asserted across a re-review attempt,
   which is rejected).
3. PDF is produced from the stored HTML, all findings expanded, masked values only.
4. Review, view, and download make zero LLM calls (asserted).

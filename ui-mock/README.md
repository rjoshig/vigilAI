# ui-mock — clickable UI mockup (Phase 1)

A **non-functional, self-contained visual prototype** of vigilAI for engineer and
stakeholder review before anything is built. Same approach as `compare-file/ui-mock/`:
plain HTML + one `styles.css` + one `app.js`, **opens from `file://`**, no build, no server,
no backend. Buttons show a toast or navigate. Demo data is invented.

Planned pages (`docs/phase-1.md` has the checklist):

| App | Page | File |
| --- | --- | --- |
| user-ui | Runs (history, status, queue position, stage progress) | `index.html` |
| user-ui | New run (form, drag-and-drop, copy from previous, duplicate-inputs dialog) | `new-run.html` |
| user-ui | Review (traceability matrix, findings, evidence panel, OK / Not OK, re-check) | `review.html` |
| user-ui | Final report (frozen one-page, PDF, clone) | `report.html` |
| user-ui | Run stats | `run-stats.html` |
| user-ui | Config history | `config-history.html` |
| admin-ui | Report templates + named values · Checks · Compliance and scope · Reference data · Usage | `admin/*.html` |

The theme tokens mirror `compare-file/ui2` so the mock and the apps look the same. No
login (out of scope in v1). Nothing here touches the apps or the toolchain.

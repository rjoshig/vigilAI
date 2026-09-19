# mock — clickable UI mock (Phase 1)

A **non-functional, self-contained visual prototype** of vigilAI for engineer and
stakeholder review before anything is built. Plain HTML + one shared `styles.css` + one
shared `app.js`, **opens from `file://`**, no build, no server, no backend. Every button
shows a toast or navigates. All data is invented (synthetic customers, orders, values).

**Start here:** open `mock/index.html` (launcher), or go straight to an app:

| App | Entry | Pages |
| --- | --- | --- |
| user-ui (`:3000`) | `user-ui/index.html` | Runs · New run (duplicate-inputs dialog, copy from previous) · Review (traceability matrix, findings + evidence drawer, OK / Not OK, bulk-OK, edit requirement / link + re-check, waterfall, attribute explorer, gated Generate) · Final report (frozen, PDF, clone) · Run stats · Config history |
| admin-ui (`:3001`) | `admin-ui/index.html` | Report templates + named values · Checks (describe → propose → test → activate; judgment "use sparingly") · Compliance & reverse-pass scope · Reference data (aliases, masked columns) · Usage |

## Layout

```
mock/
├── index.html          launcher (links to both apps and the report sample)
├── shared/styles.css   tokens copied from compare-file/ui2 (light + dark + light-blue-yellow palette) + components
├── shared/app.js       sidebar renderer, inline SVG icons, theme toggle, toast, tabs, modal, drawer
├── user-ui/            nav.js (brand + menu) + one HTML file per screen
└── admin-ui/           nav.js (brand + menu) + one HTML file per screen
```

The two apps are separate directories with their own nav so they can be reviewed (and
later re-skinned) independently; they share only the theme and the helpers.

## Re-skinning

- Colors: edit the CSS variables at the top of `shared/styles.css`, or change the
  `data-theme` attribute on `<html>` (`light-blue-yellow` is the active ui2 palette;
  remove it for the default blue).
- Brand text: `user-ui/nav.js` and `admin-ui/nav.js`.
- Light / dark: toggle in the sidebar footer; persisted in `localStorage` when allowed.

## Rules

No real customer data, sample rows, or PII anywhere in the mock (reviewed in the PR).
Nothing here touches the apps (`user-ui/`, `admin-ui/`) or the toolchain. No React.

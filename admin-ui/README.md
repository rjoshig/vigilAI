# admin-ui — the operator app (Phase 4)

A **separate** Next.js app on its own URL (**:3001**), same toolchain and theme as
`user-ui/`, no login in v1 (ADR-008). It holds report templates + named values, check
definitions (draft with the LLM once, test, version, activate), compliance rules and
reverse-pass categories, attribute aliases, masked columns, and the usage dashboard.
Rules: `standards/frontend.md`. Screens: `docs/design.md` "UI and report" and the Phase 1
mock.

Scaffolded in Phase 4 (`docs/phase-4.md`). Until then this directory holds only this file
and CI reports "not scaffolded yet". It never imports from `user-ui/`.

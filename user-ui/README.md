# user-ui — the associate-facing app (Phase 3)

Next.js 15 (App Router), TypeScript strict, Tailwind 3, npm, ESLint 8 + Prettier, Vitest.
Theme tokens and UI primitives copied from `compare-file/ui2`. Serves on **:3000** and
proxies `/api/*` to the FastAPI api (`VIGILAI_API_URL`, default `http://127.0.0.1:8000`).
Rules: `standards/frontend.md`. Screens: `docs/design.md` "UI and report" and the Phase 1
mock.

Scaffolded in Phase 3 (`docs/phase-3.md`). Until then this directory holds only this file
and CI reports "not scaffolded yet".

Planned scripts: `dev` · `build` · `start` · `lint` · `typecheck` · `format` ·
`format:check` · `test` · `test:watch`.

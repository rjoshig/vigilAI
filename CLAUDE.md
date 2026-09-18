# CLAUDE.md — How to work on this project

This file tells future Claude sessions (and humans) how to make progress on this repo
without losing context, breaking conventions, or skipping phases. It is a router: short
on purpose, it points at the durable context in `docs/` and `standards/`.

## Project in one paragraph

vigilAI automates QC validation for a credit-data fulfillment process. It reconciles three
things: the requirement spec (**OSL**, a Word document), the ETL config (JSON), and the
output reports (Excel: DIRT, distributions, counts). **The LLM reads and judges meaning;
code does every comparison.** Every OSL requirement is traced into the config and then into
the reports; findings are reviewed by a person (OK / Not OK), then a frozen one-page HTML
report with PDF download is generated. Five containers: `user-ui`, `admin-ui` (its own
URL), `api`, `worker`, `postgres`. **The full design is `docs/design.md` — it is the source
of truth for what the tool does.** See `docs/architecture.md` for how the code is laid out.

## Read first, write last

**At the start of every session, read `docs/session-log.md` first.** Its **"Resume here"**
block at the top says which phase we are in and the exact next action. If you are about
to do something that contradicts it, stop and reconcile before acting.

**At the end of every session, update the "Resume here" block and append an entry** to
`docs/session-log.md`: completed, pending, blockers, branch, next concrete action. Leave
every doc describing what is true at that commit, not what was planned — see
"Doc-driven workflow".

## Phase gating

Work proceeds in sequential phases (`docs/phase-plan.md` is the master table). Do not start
phase N+1 before phase N's acceptance criteria are met; if you think you must, ask first.
Before starting phase N, read `docs/phase-N.md` end to end.

| Phase | Theme | Doc | Status |
| --- | --- | --- | --- |
| 0 | Repo setup: structure, CLAUDE.md, docs, standards, git rules, tooling (no app code) | `docs/phase-0.md` | ✅ complete |
| 1 | Static `mock/` (user-ui, admin-ui, final report) | `docs/phase-1.md` | ✅ complete |
| 2 | Pipeline core as a CLI: parsers, rule schema, LLM adapter + cache, stages 1–9, golden set | `docs/phase-2.md` | ✅ complete (ADR-014 defers the real-model benchmark) |
| 3 | Web app: docker-compose, Postgres + queue, API, user-ui | `docs/phase-3.md` | ⬜ not started |
| 4 | admin-ui and configurable checks | `docs/phase-4.md` | ⬜ not started |
| 5 | Final one-page report, freeze, PDF | `docs/phase-5.md` | ⬜ not started |
| 6 | Hardening and in-house fit | `docs/phase-6.md` | ⬜ not started |

**This table is part of the docs and goes stale like any other.** Update it in the same
commit that changes a phase's status; `docs/phase-plan.md` must agree with it.

### Finishing a phase

The moment a phase's last task lands, in the same commit:

1. **Tick every box** in `docs/phase-N.md` — scope items and acceptance criteria alike.
   A criterion that is deliberately left open stays unticked and is labelled
   **outstanding** or **deferred**, naming the ADR that allows it. Never tick a box for
   work that was not done.
2. Set the phase doc's status line to `✅ **complete**` with the date.
3. Update the status in **both** tables: the one above and `docs/phase-plan.md`.
4. Carry any deferred criterion into the **"Resume here"** block of
   `docs/session-log.md`, so it cannot be forgotten.
5. Tick any open question in `docs/phase-plan.md` the phase answered, and record the
   answer as an ADR.
6. Stop and report to the user before starting phase N+1.

## Hard rules (from the design doc; ADR-001…008)

1. **The LLM reads and judges meaning. Code does every comparison** of values, sets,
   ranges, operators, counts, and sequences. Never ask the model to compare or compute.
2. **The OSL is the source of truth.** Config and reports are validated against it.
3. **Never put sample rows or PII in a prompt, log, fixture, or commit.** Fixtures are
   synthetic only. Logs carry ids and counts. `LLM_LOG_PROMPTS` stays false.
4. **All LLM calls go through one adapter** (`src/vigilai/llm/`). Provider, base URL, and
   model come from `.env` (`openai`-style, `anthropic`-style, `mock`). No vendor SDKs.
5. **Check the cache before every LLM call. Never send the same content twice.** Never
   regenerate a finalized report. Re-running identical inputs requires a logged reason.
6. **Parsers for the OSL, the config, and each report type sit behind interfaces**
   (Protocols), because real file layouts arrive last and only in-house.
7. **One relational database holds the data and the job queue; a shared volume holds
   files.** `DATABASE_URL` in `.env` selects it: **SQLite by default**, Postgres for
   scale (ADR-017). No MinIO, no Redis, no broker. Migrations stay portable across both.
   **No login in v1** for either UI, but keep the provision: an unused `users` table and
   one auth dependency in the API.

A PR that breaks one of these is rejected regardless of tests. Details:
`docs/llm-privacy.md`, `docs/decisions.md`.

## Doc-driven workflow

**The documentation is always current.** A doc that describes a plan the code has moved
past is worse than no doc: the next session trusts it. Docs change in the same commit as
the code they describe, never in a follow-up.

- Any non-obvious decision goes in `docs/decisions.md` as a new ADR (append-only).
- Architectural changes update `docs/architecture.md` in the same commit as the code.
- **Phase docs get checked off as tasks land**, not at the end of a phase. If you
  finished it, tick it; if you skipped it, say so and why.
- Renaming or moving anything updates every doc that names it, in the same commit
  (`grep -rn "<old name>" --include="*.md" .` before you commit).
- Docs record **what is true now**, not how we got here. No provenance notes about which
  other repos an idea came from; a decision worth keeping goes in an ADR on its own
  merits.
- Something the design doc doesn't cover: flag `# SPEC GAP:` and ask; don't guess.
- Terms: `docs/glossary.md`.
- `bash scripts/check_docs.sh` must pass before every commit.

## Local environment

- **macOS on Apple Silicon**, Docker Desktop, GitHub. Node 20+ for the UIs.
- **Python 3.10 is the floor and the pin** (`.python-version`, ADR-010). Code must run on
  3.10–3.12; don't use newer syntax or stdlib.
  ```bash
  pyenv install 3.10.14 && pyenv local 3.10.14
  python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
  ```
- LLM for local dev: Ollama's OpenAI-compatible endpoint with a Gemma model, or the
  Anthropic API — both via `.env` only (`cp .env.example .env`). Tests use `mock`.
- Postgres + everything else: `docker compose up` (from Phase 3). `docs/deployment.md`.

## Code conventions

> **Full standards live in [`standards/`](standards/) — they are canonical:**
> [`python.md`](standards/python.md), [`frontend.md`](standards/frontend.md),
> [`git.md`](standards/git.md). If this summary disagrees with them, they win.

- Type hints on every signature, Google-style docstrings, `pathlib`, `logging` (never
  `print`), no magic numbers, pure functions where possible, `argparse` CLI.
- `src/vigilai/` subpackages: `parsers/ rules/ pipeline/ checks/ llm/ db/ api/ worker/
  report/` + `cli.py`. Dependencies point down; `api/` never imports `pipeline/`.
- Pydantic v2 at boundaries only (LLM output schemas, API wire models, config).
- Prompts are versioned; the version is part of every cache key.
- Frontend: Next.js 15 App Router, TypeScript strict, Tailwind 3, npm, Vitest. Theme
  tokens copied from `compare-file/ui2`. `user-ui` :3000, `admin-ui` :3001.

## Testing

- Write tests **as you write code**. One test file per module, mirroring `src/`.
- **Synthetic fixtures only** (`tests/fixtures/`), generated by `scripts/`; never a real
  customer file. **Tests never call a real LLM** (`LLM_PROVIDER=mock` or an injected fake).
- The golden set (10–20 synthetic OSLs with known rules) runs whenever a prompt or the
  model changes.

## Lint / format / type-check

`black .` · `flake8` · `mypy src/` · `pytest` — all clean before every commit.
Frontend: `npm run lint` · `typecheck` · `format:check` · `test` · `build`.
Docs: `bash scripts/check_docs.sh`.

## Commits and branching

- Conventional Commits: `type(scope): summary` (≤72 chars); scopes in `standards/git.md`.
- No PII, customer names, or model identifiers in commit messages.
- `main` (PR-only, human merges) ← `dev` ← `feature/*`. Session branches (`claude/*`) are
  feature branches. Never push to `main`, never force-push, never rewrite history.
- CI is **manual-only** (`workflow_dispatch`); the pre-push checklist is the gate.

## What "done" means for a task

1. Code written, typed, documented. 2. Tests exist and pass. 3. `black`, `flake8`,
`mypy` (and UI gates) clean. 4. **Phase doc boxes ticked** for what landed. 5. Any ADR
the work implies is written. 6. `docs/session-log.md` "Resume here" and a new entry
updated. 7. `bash scripts/check_docs.sh` passes. 8. Commit pushed to the remote — work
that is not pushed does not count as done.

## When in doubt

Re-read `docs/design.md` and the phase doc. Re-read `docs/decisions.md` to avoid
relitigating decisions. Ask the user — cheaper than guessing wrong.

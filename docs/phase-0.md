# Phase 0 — Repo setup

**Status:** in progress (this PR). **Goal:** a repo structured like compare-file so every
later session starts from the same conventions: CLAUDE.md, docs, AI-context docs, phase
docs, coding standards, git rules, tooling and Docker/CI stubs. **No application code.**

## Scope

- [x] Directory tree (see `README.md` "Repository layout").
- [x] `CLAUDE.md` — router with the seven hard rules and links.
- [x] `README.md`, `LICENSE`, `.editorconfig`, `.gitignore`, `.env.example`, `.python-version` (3.10).
- [x] `pyproject.toml` (black / mypy strict / pytest warnings-as-errors / coverage), `.flake8`.
- [x] `standards/` — `README.md`, `python.md`, `frontend.md`, `git.md`.
- [x] `docs/design.md` — the design doc, copied verbatim.
- [x] `docs/architecture.md`, `llm-privacy.md`, `glossary.md`, `deployment.md`.
- [x] `docs/phase-plan.md` + `phase-0.md` … `phase-6.md`.
- [x] `docs/decisions.md` — ADR-001…012 seeded from the fixed decisions and this session's choices.
- [x] `docs/session-log.md` with the "Resume here" block.
- [x] `docker-compose.yml`, `docker/api.Dockerfile`, `docker/worker.Dockerfile` (stubs that parse).
- [x] `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/ci.yml` (manual-only) + README.
- [x] `scripts/check_docs.sh`, `scripts/README.md`.
- [x] `src/vigilai/` package skeleton (`__init__.py` with version, `py.typed`, subpackage READMEs — no code).
- [x] `tests/README.md`, `tests/fixtures/README.md`.
- [x] `ui-mock/`, `user-ui/`, `admin-ui/` READMEs describing what lands there and when.

## Out of scope

Any `.py` beyond the version string and the package smoke test, any Next.js scaffold, any fixture file, any real
Dockerfile logic beyond `pip install -e .`.

## Exit criteria

1. All files above present; `docs/design.md` is byte-identical to the design doc export.
2. `pip install -e ".[dev]"` succeeds; `pytest` passes (one package smoke test);
   `black --check .`, `flake8`, `mypy src/` clean.
3. `docker compose config` parses.
4. `bash scripts/check_docs.sh` passes.
5. PR "Phase 0: repo setup" open against `main` with the reference conflicts noted.
6. After merge (human): create `dev` from `main`; later feature branches target `dev`.

## Borrowed from the references

- **compare-file** (primary): CLAUDE.md format, `standards/` set and content, `docs/`
  layout, single append-only `decisions.md`, `phase-plan.md` + `phase-N.md` format,
  `session-log.md` format, pyproject / flake8 / gitignore, `ui-mock/` approach, `ui2`
  frontend toolchain and theme.
- **snopfamily** (secondary): PR template, SHA-pinned manual-only CI, "Resume here"
  block, glossary, docs integrity script, "session branches are feature branches", "no
  model identifiers in commits".

## Reference conflicts and how they were resolved

| Topic | compare-file | snopfamily | vigilAI |
| --- | --- | --- | --- |
| Branch names | bans agent-prefixed branches | session branches are feature branches | snopfamily rule (the hosted tooling assigns `claude/*`); recorded in `standards/git.md` §1 |
| CI | none | Actions, manual-only | snopfamily (user choice, ADR-012) |
| Frontend | npm, React 18, Tailwind 3, ESLint 8, no tests | pnpm, React 19, Tailwind 4, ESLint 9, Vitest | compare-file stack + Vitest (user choice, ADR-011) |
| ADRs | one file | one file per ADR | compare-file |
| Python floor | 3.10+, dev pinned 3.12 | — | 3.10 floor **and** pin (user choice, ADR-010) |

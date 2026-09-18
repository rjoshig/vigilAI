# Phase 0 — Repo setup

**Status:** ✅ **complete** (2026-09-18). **Goal:** a repo where every later session
starts from the same conventions: CLAUDE.md, docs, phase docs, coding standards, git
rules, tooling and Docker/CI stubs. **No application code.**

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
- [x] `mock/` (was `ui-mock/`, ADR-013), `user-ui/`, `admin-ui/` READMEs describing what lands there and when.

## Out of scope

Any `.py` beyond the version string and the package smoke test, any Next.js scaffold, any fixture file, any real
Dockerfile logic beyond `pip install -e .`.

## Exit criteria

1. [x] All files above present; `docs/design.md` is byte-identical to the design doc
   export.
2. [x] `pip install -e ".[dev]"` succeeds; `pytest` passes; `black --check .`, `flake8`,
   `mypy src/` clean.
3. [x] `docker compose config` parses.
4. [x] `bash scripts/check_docs.sh` passes.
5. [x] PR "Phase 0: repo setup" open against `main`.
6. [ ] **Outstanding (human):** merge the PR, then create `dev` from `main`; later
   feature branches target `dev`.

## Choices settled during setup

| Topic | vigilAI |
| --- | --- |
| Branch names | Session branches (`claude/*`) are feature branches; `standards/git.md` §1 |
| CI | GitHub Actions, manual-only (ADR-012) |
| Frontend | npm, Next.js 15, React 18, Tailwind 3, plus Vitest (ADR-011) |
| ADRs | One append-only `decisions.md` (ADR-009) |
| Python | 3.10 is the floor **and** the pin (ADR-010) |

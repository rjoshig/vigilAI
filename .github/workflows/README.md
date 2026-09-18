# .github/workflows/

One workflow, `ci.yml`, **manual-only** (`workflow_dispatch`) by owner decision — see
ADR-012 in [`docs/decisions.md`](../../docs/decisions.md). The local pre-push checklist in
[`standards/git.md`](../../standards/git.md) §3 is the real gate; dispatch this workflow by
hand before a merge to `main`. Actions are pinned by commit SHA where a verified SHA was available (setup-python still uses a tag; see the TODO). No secrets: tests run
with `LLM_PROVIDER=mock`.

| Job | What it runs |
| --- | --- |
| `python` | `black --check .` · `flake8` · `mypy src/` · `pytest` against a Postgres 16 service |
| `ui` (matrix user-ui, admin-ui) | `npm run lint` · `typecheck` · `format:check` · `test` (Vitest) · `build`; passes with a notice until the app is scaffolded |
| `docs` | `bash scripts/check_docs.sh` — relative links resolve, every `docs/` file is indexed in `README.md` |

Restore `pull_request` and `push: branches: [main]` triggers when the owner says so.

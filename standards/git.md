# Git & Workflow Standards

How we branch, commit, and open PRs. These rules are **canonical**; `CLAUDE.md` keeps a
short summary and links here. Adapted from `compare-file/standards/git.md` with two rules
borrowed from `snopfamily/AI_CONTEXT/GIT_RULES.md` (session branches, no model identifiers).

This repo is a **Python service** (`src/vigilai/`: pipeline, worker, CLI, FastAPI) plus
**two Next.js apps** (`user-ui/`, `admin-ui/`). CI exists but is **manual-only** (ADR-012),
so the local **pre-push checklist (§3) is the gate** — mandatory, not advisory.

---

## 1. Branch strategy

- **`main`** — stable, releasable. Never commit or push directly. Receives merges from `dev`
  via PR only. Claude Code may open the `dev → main` PR at the user's request, but **only
  the human merges it.**
- **`dev`** — integration / active development. Small changes land here directly (see
  thresholds); larger ones come via `feature/*` → `dev`. (`dev` is created from `main`
  after the Phase 0 PR merges; until then feature branches target `main`.)
- **`feature/<short-kebab-desc>`** — medium/large changes. Branch off `dev`, merge back via
  PR. Example: `feature/osl-parser`.
- **`fix/<short-desc>`** — an isolated bug fix too big for direct-to-dev.
- **`experiment/<short-desc>`** — exploratory only; **never merges**. Delete when concluded.
- **Session branches** created by the remote tooling (`claude/<slug>`) are **treated as
  feature branches** and merged through a PR like any other. (Deviation from compare-file,
  which bans agent-prefixed names: the hosted tooling assigns them. Don't create such names
  by hand.)

**Promotion flow:** `feature/*` → `dev` → `main`. Every merge is a PR, squash-merged.
Claude Code never pushes to `main` and never merges.

**Naming:** kebab-case after the type prefix. Good: `feature/llm-cache`,
`fix/xlsx-label-lookup`. Bad: `my-stuff`, `phase3`.

### Feature-branch lifecycle
- Merge when the feature is complete, or by ~30 commits — whichever comes first. Past that
  and not done: **stop, report, reassess scope.**
- The **human** deletes branches after merge.

### When Claude Code may commit directly to `dev`
Only if **all** hold: fewer than 5 files · no schema/migration change (`src/vigilai/db/`) ·
no API contract change (`src/vigilai/api/` routes or wire models) · no cross-subpackage
change (§5) · not a refactor. Otherwise → `feature/*` first.

### Max change size
More than **8 files** or **400 lines** (cumulative) → `feature/*`, never a mega-change on
`dev`. If you realise mid-task you're crossing the limit: stop, branch, continue there.

---

## 2. Commit rules

**Format:** `type(scope): short description in present tense` — first line ≤ 72 chars,
body explains **why** and what behaviour changed.

**Types:** `feat` · `fix` · `chore` · `test` · `refactor` · `docs` · `perf`.

**Scopes:** `parsers`, `rules`, `pipeline`, `checks`, `llm`, `db`, `api`, `worker`,
`report`, `cli`, `user-ui`, `admin-ui`, `ui-mock`, `docs`, `tests`, `tooling`, `docker`,
`ci`, `deps`, `repo`.

**Examples:**
```
feat(llm): add openai-compatible client behind LLMClient protocol
feat(pipeline): stage 5 compares intervals and reports operator mismatches
fix(parsers): label lookup tolerates trailing spaces in report cells
docs(decisions): add ADR-013 for expression evaluator sandboxing
test(rules): cover derived checks for every operator
chore(repo): phase 0 scaffold
```

**Rules:**
- **One concern per commit.** Group by logical unit (one module + its tests, or one config
  change). Commit after each meaningful unit of work, not at end of session.
- Reference the relevant **ADR** in the body when the commit encodes a decision; update
  `docs/architecture.md` in the same commit as an architectural change.
- **Never commit broken code.** All of §3 must pass first, and the app must still start.
- **Never commit** generated/runtime artifacts (`data/`, `__pycache__/`, `.venv/`,
  `node_modules/`, `.next/`, `*.db`) or secrets (`.env`, `.env.*`, keys). Check
  `git status` before `git add`.
- **Never commit real customer data** — no OSL, config, report, or sample row that came
  from a real job, even "anonymized". Fixtures are synthetic (ADR-003).
- The standard Claude Code co-author / session trailers are allowed. **No model
  identifiers** in commit messages, PR text, or code comments.
- Each commit touches **only** the files relevant to its stated purpose.

---

## 3. Pre-push checklist (mandatory — CI is manual-only)

Run **all** of these before every push, on any branch. If any fails, fix it before pushing.

**Python (if `src/` or `tests/` changed):**
- [ ] `black --check .` · [ ] `flake8` · [ ] `mypy src/` · [ ] `pytest`

**Frontend (per app, if `user-ui/` or `admin-ui/` changed):**
- [ ] `npm run lint` · [ ] `npm run typecheck` · [ ] `npm run format:check` ·
  [ ] `npm test` · [ ] `npm run build`

**Docs (if any `.md` changed):**
- [ ] `bash scripts/check_docs.sh`

**Hygiene (always):**
- [ ] `git status` — no `.env*`, `data/`, `*.db`, `node_modules/`, `.next/` staged
- [ ] `git diff --staged` — no secrets, tokens, API keys, customer names, or sample rows
- [ ] commit message follows §2 and contains no PII
- [ ] no bare `TODO` / `FIXME` / `HACK` — use the flag format below

**Never push and rely on review to catch failures.**

### TODO / flag format
- Allowed: `# TODO(human): confirm grace period` / `// TODO(human): ...`
- To flag for human review:
  `# PRODUCT DECISION NEEDED: <file:line> <description>`,
  `# SPEC GAP: <file:line> <description>` (the design doc doesn't cover it),
  `# ADR NEEDED: <description>`.

---

## 4. What Claude Code may / may not do in git

**Allowed without asking:**
```
git status · git diff · git diff --staged · git log --oneline
git branch --show-current · git fetch origin
git checkout <existing-branch> · git checkout -b feature/<desc>   (when §1 requires)
git add <explicit file paths>          # never wildcards
git commit -m "type(scope): ..."       # §2 format
git push -u origin <current branch>    # only after §3 fully passes
```

**Never run without explicit human instruction:**
```
git add . / git add -A / git add *
git push origin main
git push --force / --force-with-lease  (exception: restarting an already-merged session
                                        branch from main, see §11)
git merge / git rebase / git rebase -i
git reset --hard / --soft
git revert · git cherry-pick · git tag · git commit --amend
git branch -d / -D · git stash
```

If unsure whether a git operation is safe: **stop, describe the situation, ask.**

---

## 5. One-subpackage-per-task rule

Don't modify more than one subpackage of `src/vigilai/` (or one UI app) in a single task
unless the task explicitly requires it. If it must cross boundaries, say so before writing
code:
> "This task requires changes to: [subpackages] because [reason]."

and wait for confirmation.

---

## 6. Pull requests

- **Claude Code may open PRs** at the user's request. It never pushes to `main` and never
  merges. Use `.github/PULL_REQUEST_TEMPLATE.md`.
- **When:** `dev → main` when a phase/milestone is complete and verified locally;
  `feature/* → dev` when the feature is complete.
- **Never** open a PR with failing checks or unresolved `PRODUCT DECISION NEEDED` /
  `ADR NEEDED` flags.
- **Merge strategy:** squash merge, linear history.
- If an API endpoint, wire model, or DB schema changes, say so in the PR and keep
  `docs/architecture.md` / the phase doc in sync.

---

## 7. Checks & stability

- CI (`.github/workflows/ci.yml`) is **dispatched by hand** before a merge to `main`. Never
  disable a lint rule or delete assertions to make checks pass — fix the root cause.
- **`dev` stability:** `dev` is unstable if `pytest` fails, `mypy`/`flake8` error, the API
  won't start, or a UI won't build. If `dev` is unstable: **stop feature work, fix it.**

---

## 8. Architecture, refactor & change discipline

- **Implement the design doc faithfully** (`docs/design.md`). No speculative improvements
  or "while I'm in here" changes. Flag better ideas with `# SUGGESTION:` and let the human
  decide.
- **No architecture drift.** Don't change subpackage boundaries, add a framework or
  dependency not already planned, or change an API shape / DB schema without the design
  requiring it **and** human confirmation. Flag `# ADR NEEDED` and record the decision.
- **The hard rules in `CLAUDE.md` are not negotiable in a PR.** A change that routes an
  LLM call around the adapter or cache, puts PII in a prompt or log, regenerates a
  finalized report, or reintroduces Redis/MinIO/login is rejected.
- **Refactors are isolated:** behaviour-preserving only; tests pass before and after.

---

## 9. Schema / data safety (Postgres + shared volume)

The schema lives in `src/vigilai/db/` (SQLAlchemy models + Alembic migrations). Without
explicit human approval, never:
- drop or rename a table or column,
- change an id format, a `status` vocabulary, or a count column's meaning,
- delete files on the shared volume outside the retention purge,
- touch `final_reports` rows or files (a finalized report is frozen, ADR-005).

Schema changes are **additive, migrated with Alembic, and reversible**. New settings are
optional with a default.

---

## 10. Commit-message sanitization (critical)

Commit messages must **not** contain emails, phone numbers, person or place names,
customer identifiers, order numbers, secrets, or any PII. Describe behaviour, not data.

---

## 11. Conflicts, rejected pushes, paused work, merged session branches

- **Merge conflict:** do **not** auto-resolve. Stop, report, ask. After resolution re-run §3.
- **Rejected push (non-fast-forward):** do **not** force-push. Stop, report, ask.
- **Session ends mid-task:** leave partial work **uncommitted** and record state in
  `docs/session-log.md`. Never commit half-finished work just to "save progress."
- **A session branch whose PR already merged:** restart the same branch name from the
  latest default branch (`git fetch origin main && git checkout -B <branch> origin/main`)
  and open a **new** PR; never stack commits on merged history.

---

## 12. Session & phase workflow

- **Start of session:** read [`../docs/session-log.md`](../docs/session-log.md) — its
  "Resume here" block is where you pick up.
- **Phase gating:** work proceeds in sequence ([`../docs/phase-plan.md`](../docs/phase-plan.md));
  don't start a later phase before the current one's acceptance criteria are met — ask first.
- **Decisions:** non-obvious choices get a new ADR in
  [`../docs/decisions.md`](../docs/decisions.md); architectural changes update
  [`../docs/architecture.md`](../docs/architecture.md) in the same commit.
- **End of session:** update the "Resume here" block and append a `docs/session-log.md`
  entry (completed, pending, blockers, branch, next concrete action).

---

## Definition of done (before the final commit/push)

1. Code written, typed, documented.
2. Tests exist and pass (synthetic fixtures, mock LLM).
3. Pre-push checklist (§3) green — Python **and** any UI touched.
4. Relevant phase doc updated.
5. `docs/session-log.md` updated.
6. Commit pushed to `dev` or the feature branch (never `main`).

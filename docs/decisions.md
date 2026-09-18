# Architectural Decision Records

Each entry follows: **Title**, **Status**, **Context**, **Decision**, **Consequences**.
Decisions are append-only — supersede an old one by adding a new entry that references it,
never by editing in place. ADR-001…008 restate the fixed decisions from
[`design.md`](design.md) so code can cite them; ADR-009…012 record choices made during
repo setup.

---

## ADR-001 — The LLM reads and judges meaning; code does every comparison

**Status:** accepted (design doc)

**Context:** Reconciling an OSL, a config, and reports needs both semantic judgment
("does this config block implement this requirement?") and exact value checks (sets,
intervals, counts). A mid-size in-house model is unreliable at arithmetic and comparison.

**Decision:** The LLM extracts requirements, describes config blocks, judges one narrow
question per unclear pair, verifies high-severity findings, and writes the summary. Every
comparison of values, sets, ranges, operators, counts, and sequences is deterministic
Python (`rules/`, `pipeline/s5…s7`, `checks/`). Never ask the model to compute.

**Consequences:** Results are exact, repeatable, and auditable. The canonical rule schema
(ADR-006 companion in `rules/`) is the contract that makes comparison "simple code".
Re-check after a user edit needs no LLM.

---

## ADR-002 — The OSL is the source of truth

**Status:** accepted (design doc)

**Context:** Three artifacts can disagree; one must win.

**Decision:** Config and reports are validated against the OSL. The forward pass traces
every OSL requirement into the config and then into the reports. The reverse pass is
scoped (filters / select criteria, model data, compliance rules) because the OSL does not
describe every detail of the extract.

**Consequences:** "Extra rule in config" is Medium severity; "rule missing in config" is
High. Compliance rules are the one exception that must exist even if the OSL is silent.

---

## ADR-003 — No sample rows or PII in prompts, logs, fixtures, or commits; fixtures are synthetic

**Status:** accepted (design doc)

**Context:** The DIRT sample tab may hold real PII. The tool is internal but the LLM
endpoint, logs, and the git history are all places data can leak.

**Decision:** The model sees OSL text, config JSON, and findings (field names, thresholds,
aggregates) only. Sample rows are masked at parse time from an admin-maintained column
list and never enter a prompt. Logs carry ids and counts. `LLM_LOG_PROMPTS` is a dev-only
switch for synthetic data. `tests/fixtures/` is generated from invented values; no real
customer file, or anything derived from one, enters the repo. `.gitignore` blocks
`*.docx`/`*.xlsx` outside `tests/fixtures/`.

**Consequences:** Real-layout parser work happens in-house (Phase 6) on a machine that
never pushes those files. A PII regex tripwire on assembled prompts is added in Phase 6 as
defense in depth.

---

## ADR-004 — One LLM adapter; provider, base URL, and model from `.env`; no vendor SDKs

**Status:** accepted (design doc)

**Context:** Production is an air-gapped in-house model behind an OpenAI-style or
Anthropic-style API; dev uses Ollama or the Anthropic API; tests need no model at all.

**Decision:** `src/vigilai/llm/` is the only module that talks to a model, through the
`LLMClient` Protocol. `OpenAIClient` (`/chat/completions`), `AnthropicClient`
(`/v1/messages`), and `MockClient` are selected by `LLM_PROVIDER`; URL, key, model,
limits, and concurrency come from the environment. Plain `httpx`, no SDKs. JSON-only
output validated by Pydantic with one retry.

**Consequences:** Switching model or provider is an `.env` change and a worker restart.
Every call writes an `llm_calls` row, which is where tool stats come from.

---

## ADR-005 — Cache before every LLM call; never send the same content twice; never regenerate a finalized report; reruns need a logged reason

**Status:** accepted (design doc)

**Context:** LLM cost must stay low and results must be reproducible.

**Decision:** `llm_cache` keyed by `sha256(content) + model + prompt version` is checked
before every call; a miss is the only path to the network. A run fingerprint (inputs +
active check versions) returns the existing run unless the user supplies a `rerun_reason`,
which is logged. `finalize` renders the report once; the stored HTML is never regenerated
and the PDF is rendered from it. Review, re-check, view, and download never call the LLM.
`LLM_MAX_TOKENS_PER_RUN` stops a runaway run.

**Consequences:** Prompt templates carry a version constant; bumping it is how prompt
changes take effect. Cache entries hold no sample rows and expire with retention.

---

## ADR-006 — Parsers sit behind interfaces

**Status:** accepted (design doc)

**Context:** The real OSL template, config style, and report layouts are only available
in-house and arrive last. Everything before that runs on synthetic fixtures.

**Decision:** `OslParser`, `ConfigParser`, and one `ReportParser` per report type are
`typing.Protocol`s in `parsers/base.py`. The pipeline imports the Protocols. First
implementations target the synthetic fixtures; Phase 6 swaps implementations, not call
sites.

**Consequences:** Parsed-document dataclasses are the stable contract; a new report type
is a new parser + a new `req_type` check, nothing else.

---

## ADR-007 — Postgres for data and the job queue; shared Docker volume for files; no MinIO, no Redis

**Status:** accepted (design doc)

**Context:** Single host, ~80 concurrent users, LLM-bound throughput. Every extra service
is operational load on an internal team.

**Decision:** Postgres 16 holds every table plus the Procrastinate queue (`LISTEN/NOTIFY`
+ row locks; jobs survive restarts; 3 retries with backoff). Files live on one Docker
volume mounted into api and worker; the DB stores paths and hashes. Five containers in one
docker-compose.

**Consequences:** Scale workers with `--scale worker=N`. If workers ever move to a second
host, switch the volume to NFS or add an object store then — a new ADR.

---

## ADR-008 — No login in v1; keep the provision (unused `users` table, one auth dependency)

**Status:** accepted (design doc)

**Context:** Internal network only; no per-person attribution needed in v1. Login may come
later, to the admin-ui first.

**Decision:** Neither UI has login. The api has exactly one FastAPI auth dependency, used
by every router, that is a no-op in v1. The `users` table exists and stays empty. Runs,
decisions, and rerun reasons are tied to the run ID and timestamps; `audit_log.user_id` is
nullable.

**Consequences:** All runs are visible to everyone on the internal network; sample rows
stay masked everywhere with no unmask option. Adding login later touches the dependency
and the UIs, not the endpoints.

---

## ADR-009 — Repo structure follows compare-file; branching main / dev / feature; session branches are feature branches

**Status:** accepted 2026-09-18 (repo setup)

**Context:** The user wants vigilAI structured like `rjoshig/compare-file` (primary
reference) with good practices from `rjoshig/snopfamily` (secondary). The two conflict on
branch naming: compare-file bans agent-prefixed branches; the hosted tooling assigns
`claude/<slug>` session branches.

**Decision:** Layout, `CLAUDE.md` format, `standards/`, `docs/` with a single append-only
`decisions.md`, `phase-plan.md` + `phase-N.md`, `session-log.md`, and the `ui-mock/`
approach follow compare-file. Branching is `main` ← `dev` ← `feature/*`, squash merges,
human merges. Session branches created by the tooling are treated as feature branches
(snopfamily rule); nobody creates such names by hand. Borrowed from snopfamily: the PR
template, the "Resume here" block, `glossary.md`, the docs integrity script, and "no model
identifiers in commits".

**Consequences:** The Phase 0 PR targets `main` (no `dev` yet); `dev` is created from
`main` after it merges. Recorded in `standards/git.md`.

---

## ADR-010 — Python 3.10 is the floor and the pin

**Status:** accepted 2026-09-18 (user decision)

**Context:** compare-file supports 3.10+ and pins the dev box to 3.12. The user asked for
3.10 compatibility with 3.10 pinned, so nothing newer creeps in.

**Decision:** `requires-python >= 3.10`; `.python-version` pins 3.10.x; black targets
py310–py312; mypy `python_version = "3.10"`. Docker images use `python:3.10-slim`. No
3.11+ syntax or stdlib (`except*`, `typing.Self`, `tomllib`, PEP 701 f-strings).

**Consequences:** Code runs on 3.10–3.12. Tooling that needs 3.11+ is out.

---

## ADR-011 — Frontend stack: compare-file ui2 toolchain plus Vitest

**Status:** accepted 2026-09-18 (user decision)

**Context:** compare-file ui2 uses npm, Next.js 15, React 18, Tailwind 3, ESLint 8,
Prettier, and has no unit tests; snopfamily uses pnpm, React 19, Tailwind 4, ESLint 9
flat config, Vitest. The design doc requires the ui2 look and feel.

**Decision:** Both apps use the ui2 toolchain and copy its theme tokens and UI primitives,
plus Vitest + Testing Library for unit tests. `user-ui` on :3000, `admin-ui` on :3001,
no shared package between them.

**Consequences:** The look matches with no theme porting. Upgrading to React 19 / Tailwind
4 later is a new ADR.

---

## ADR-012 — CI is GitHub Actions, manual-only

**Status:** accepted 2026-09-18 (user decision)

**Context:** compare-file has no CI; snopfamily has Actions but runs them only on
`workflow_dispatch` to conserve Actions credit.

**Decision:** `.github/workflows/ci.yml` exists with the full gate set (Python, both UIs,
docs) but triggers only on `workflow_dispatch`. The local pre-push checklist in
`standards/git.md` §3 is the gate; the workflow is dispatched by hand before a merge to
`main`. Tests run with `LLM_PROVIDER=mock`.

**Consequences:** Never open a PR just to run CI. Restore `pull_request` / `push` triggers
only when the user says so.

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

## ADR-007 — One relational database for data and the job queue; shared volume for files; no MinIO, no Redis

**Status:** accepted (design doc) · **amended by ADR-017** (the database is selectable:
SQLite by default, Postgres by configuration)

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

## ADR-009 — Repo layout and branching: main / dev / feature, with session branches as feature branches

**Status:** accepted 2026-09-18 (repo setup)

**Context:** The repo needs a documentation layout and a branching model that work with
hosted tooling, which assigns `claude/<slug>` session branch names rather than letting a
developer choose them.

**Decision:** A single append-only `decisions.md`, `phase-plan.md` plus one
`phase-N.md` per phase, `session-log.md` with a "Resume here" block, `glossary.md`, a
docs integrity script, `standards/`, and the static `mock/`. Branching is `main` ←
`dev` ← `feature/*`, squash merges, human merges. Session branches created by the
tooling are treated as feature branches; nobody creates such names by hand. Commit
messages carry no model identifiers.

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

**Context:** The design doc requires the compare-file ui2 look and feel, so both apps
adopt its toolchain: npm, Next.js 15, React 18, Tailwind 3, ESLint 8, Prettier. That
toolchain ships no unit tests, which this project needs.

**Decision:** Both apps use the ui2 toolchain and copy its theme tokens and UI primitives,
plus Vitest + Testing Library for unit tests. `user-ui` on :3000, `admin-ui` on :3001,
no shared package between them.

**Consequences:** The look matches with no theme porting. Upgrading to React 19 / Tailwind
4 later is a new ADR.

---

## ADR-012 — CI is GitHub Actions, manual-only

**Status:** accepted 2026-09-18 (user decision)

**Context:** CI should exist for a pre-merge check but must not consume Actions credit
on every push.

**Decision:** `.github/workflows/ci.yml` exists with the full gate set (Python, both UIs,
docs) but triggers only on `workflow_dispatch`. The local pre-push checklist in
`standards/git.md` §3 is the gate; the workflow is dispatched by hand before a merge to
`main`. Tests run with `LLM_PROVIDER=mock`.

**Consequences:** Never open a PR just to run CI. Restore `pull_request` / `push` triggers
only when the user says so.

## ADR-013 — UI mock lives in `mock/` with `user-ui/` and `admin-ui/` as separate directories

**Status:** accepted 2026-09-18 (user decision)

**Context:** Phase 0 planned a single flat `ui-mock/` with admin pages under `admin/`. The
user wants the two apps reviewable as separate mocks, mirroring the two real apps
(`user-ui/` on :3000, `admin-ui/` on :3001, each with its own nav), and asked for the
directory to be renamed to `mock/`.

**Decision:** `mock/index.html` (launcher) · `mock/shared/` (`styles.css` with the ui2
tokens, `app.js` with sidebar / icons / theme / toast / tabs / modal / drawer) ·
`mock/user-ui/` and `mock/admin-ui/`, each with its own `nav.js` and one HTML file per
screen. Still static, still `file://`, still no build. Commit scope `mock` replaces
`ui-mock`.

**Consequences:** Phase 1 docs, README, standards, and CLAUDE.md reference `mock/`.
`docs/design.md` keeps the phrase "ui-mock" because it is the design doc verbatim.

## ADR-014 — Phase 2 is built and validated against `LLM_PROVIDER=mock`; the Gemma benchmark is deferred

**Status:** accepted 2026-09-18 (user decision)

**Context:** Phase 2 milestone 2f calls for running the golden set against a local Gemma
via Ollama and recording accuracy in `docs/benchmarks/phase-2.md`. No local model is set
up on the development machine yet, and the user asked to proceed with the mock provider.

**Decision:** All of Phase 2 is written and tested against `LLM_PROVIDER=mock`, including
the golden-set harness, which must run end to end on the mock. The real-model benchmark
(phase-2 acceptance criterion 2) is deferred: `scripts/golden_set.py` is provider-agnostic
so the numbers can be produced later with one command and no code change.

**Consequences:** Phase 2 can complete every criterion except the recorded Gemma numbers.
That criterion stays open in `docs/phase-2.md` and must be closed before Phase 6
("in-house fit"). Prompt wording is therefore unvalidated against a real model until then;
treat the prompt versions as provisional and expect a bump after the first Gemma run.

## ADR-015 — The finalize gate is: every high-severity finding needs a decision

**Status:** accepted 2026-09-18 (user decision)

**Context:** `design.md` "Review and final report" proposes the gate but leaves it open;
it was one of the open questions in `docs/phase-plan.md`.

**Decision:** "Generate final report" is enabled only when every finding with severity
High has a review decision (OK or Not OK). Medium and Low findings may be left undecided,
and Low findings can be decided in bulk. The gate is enforced in the API at finalize time,
not only in the UI.

**Consequences:** The mock already shows this behaviour. The gate is a named constant, not
a magic value, so it can be tightened later (the admin-ui Compliance screen mocks a
selector for it) without a schema change.

## ADR-016 — Stage 5 compares waterfall order on shared steps only; extra config steps belong to the reverse pass

**Status:** accepted 2026-09-18

**Context:** An OSL states the processing order in prose ("process in this order:
geography, then score, then age, then exclusions, then dedupe"). A config's step list
also carries boundary markers the OSL never mentions, such as the `input` step, and may
add steps of its own. Comparing the two lists literally reported an order mismatch on
every run, which would have trained reviewers to ignore the finding type entirely.

**Decision:** Stage 5 compares the relative order of the steps the OSL and the config
*share*. A step the OSL requires and the config lacks is reported as
`rule_missing_in_config` (High). A step present only in the config is **not** a stage 5
finding: it is an extra config element, which is the scoped reverse pass's job in stage 6
(`docs/design.md` "Processing pipeline", step 6). Step names are compared
case-insensitively.

**Consequences:** A genuine reordering and a genuinely missing step are still caught.
An extra config step is still surfaced, but by stage 6 and against the reverse-pass
category list, so an admin can scope it. If in-house configs turn out to name the same
step differently from the OSL (for example `suppress` against `exclusions`), the step
names need the alias table too; that is a `# SPEC GAP:` to confirm against real files in
Phase 6.


## ADR-017 — The database is selectable from `.env`: SQLite by default, Postgres for scale

**Status:** accepted 2026-09-18 (user decision) · amends ADR-007

**Context:** ADR-007 fixed the store as Postgres 16 with a Procrastinate queue. In
practice most work on this project happens on a laptop, and requiring Docker and a
running Postgres to execute a test, a migration, or a single run is friction on every
task. The user asked for SQLite by default with Postgres available by flipping one
switch in `.env`.

**Decision:** One setting, `DATABASE_URL`, chooses the backend, and nothing else in the
code or the compose file changes:

```bash
DATABASE_URL=sqlite+pysqlite:///./data/vigilai.db            # default
DATABASE_URL=postgresql+psycopg://vigilai:vigilai@postgres:5432/vigilai
```

Three consequences follow, and each is handled rather than papered over:

1. **Column types.** JSON columns are declared `JSON().with_variant(JSONB, "postgresql")`
   so Postgres still gets indexable `jsonb` and SQLite gets portable `json`. Timestamps
   are timezone-aware on both.
2. **The queue.** Procrastinate is Postgres-only, so it is dropped. The queue is an
   ordinary `jobs` table in whichever database is configured, claimed with
   `FOR UPDATE SKIP LOCKED` on Postgres and with a guarded single-statement `UPDATE` on
   SQLite, which is safe because SQLite serialises writers. Retries, backoff, and
   resume-from-last-good-stage are our own code either way, and they were going to be
   ours regardless. This removes a dependency rather than adding one, and there is still
   no Redis and no broker.
3. **Concurrency.** SQLite takes one writer at a time. It is right for a laptop, a demo,
   and a single-worker in-house pilot; it is not right for several workers under load.
   `docker compose up` therefore still runs Postgres, and the compose file sets
   `DATABASE_URL` to it. SQLite is the default for everything outside Docker.

**Consequences:** Tests, migrations, the CLI, and a single-worker run need no Docker.
The choice is one line in `.env` and is logged at startup, so a deployment cannot be
confused about which store it is using. Alembic migrations must stay portable: additive
changes only, no Postgres-only DDL, and both backends are exercised in the test suite.
Anything that genuinely needs Postgres (a partial index, `LISTEN/NOTIFY`) needs a new
ADR and a documented fallback for SQLite.

## ADR-018 — A PII tripwire on every prompt, failing closed

**Status:** accepted 2026-09-18 (Phase 6)

**Context:** ADR-003 says no sample row or PII reaches a prompt, and masking at parse
time is how that is enforced. That is the right place for it, but it is one layer: a new
stage that assembles its own text, a fixture that leaks, or a parser change that stops
masking a column would all defeat it silently. Phase 6 asks for a tripwire on every
assembled prompt.

**Decision:** `vigilai/llm/tripwire.py` scans every assembled prompt inside the adapter,
before the cache lookup and therefore before any path to the network. It matches
formats, not meanings: SSN, card number, email, phone, street address, and a labelled
date of birth. On a match it **raises**, and the prompt is not sent.

Three details that make it usable rather than theatre:

- **It fails closed.** A prompt already sent cannot be recalled, so the cost of a false
  positive (a failed run with a clear message) is far below the cost of a false negative
  (customer data in a third party's logs).
- **The patterns are narrow.** A "looks like a name" rule would fire on ordinary
  requirement text and teach people to switch the tripwire off, which is worse than not
  having one. The test suite asserts that ten samples of real pipeline text pass.
- **The error carries no value.** Matches are reported by pattern name, position, and a
  redacted shape. The exception message reaches logs, and logs hold ids and counts only.

It runs before the cache so the answer cannot depend on whether the same content was
seen before. `LLM_PII_TRIPWIRE=false` exists for a deployment that must, and a single
pattern can be disabled individually, which is the right response to a false positive.

**Consequences:** Every prompt pays a handful of regex scans, which is nothing beside a
model call. A deployment whose own data legitimately matches a pattern narrows that
pattern rather than disabling the tripwire. The masked-column list remains the primary
control; this is the backstop that says when it has failed.

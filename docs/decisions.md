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

**Decision:** `src/greenlight_ai/llm/` is the only module that talks to a model, through the
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
DATABASE_URL=sqlite+pysqlite:///./data/greenlight-ai.db            # default
DATABASE_URL=postgresql+psycopg://greenlight_ai:greenlight_ai@postgres:5432/greenlight_ai
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

**Decision:** `greenlight_ai/llm/tripwire.py` scans every assembled prompt inside the adapter,
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

## ADR-019 — A dormant Phase 7 for fitting the tool to the real files

**Status:** accepted 2026-09-18 (user decision)

**Context:** `design.md` plans six phases, and Phase 6 folds "adapt parsers to real
samples in-house" into a general hardening phase. In practice that work is different in
kind from the rest of Phase 6: it happens on a **different machine**, at an unknown
time, driven by files that cannot come here, and it is conversational rather than
planned — the user shows Claude a real artifact and asks what needs to change. Leaving
it inside Phase 6 meant a phase that could never be completed and a checklist that
could never be written honestly.

**Decision:** Add `docs/phase-7.md`, "Real-world fit", with three properties that make
it different from every other phase:

1. **Dormant.** It runs only on an explicit request. No phase depends on it, nothing
   schedules it, and a session that notices it must not act on it. Both phase tables
   and `CLAUDE.md` say so.
2. **Conversational.** Its unit of work is one artifact and one question: "look at this
   file and tell me what needs to change". The doc specifies the loop — read it with
   the existing parser, name the gaps, say what changes and where, say what does *not*
   change, propose the fixture, then **stop** — rather than a task list, because the
   findings cannot be known in advance.
3. **Bounded by ADR-003.** Its first section is the rule that a real customer file, or
   anything derived from one, never enters the repository. It defines what may come
   back out (shapes, counts, patterns, synthetic fixtures modelled on a shape) against
   what may not (any value, any row, any identifier), and requires the real files to
   live outside the working tree.

Phase 6 keeps the items its own teams own — TLS, encrypted volumes, retention sign-off,
the load test at real concurrency — and hands the file-shaped work to Phase 7.

**Consequences:** Phase 6 can be finished by the platform and compliance teams without
waiting for files. Phase 7 can sit dormant indefinitely without making the plan look
stalled. The phase doc carries the per-artifact assumption tables — what the parsers
believe today and what would break each belief — so the analysis starts from what the
code actually does rather than from a blank page. Those tables are derived from the
code and **go stale when the parsers change**; whoever changes a parser assumption
updates the matching row, the same rule as every other doc.

## ADR-020 — Artifact types, their meaning, and run scope are admin data

**Status:** accepted 2026-09-18 (user decision)

**Context:** The tool shipped with a fixed set of seven report types, compiled into
`ReportKind`, into the upload form, and into the admin screens. Two things were wrong
with that. Customers send reports we have not met, so a new one meant a code change and
a deploy. And nothing anywhere said what a report *means*: the model saw a workbook and
inferred its purpose from its contents, which is exactly the kind of guessing ADR-001
exists to avoid. The same gap applied to the OSL and the ETL config, and to the
delivery programme — Account Monitoring, Account Solicitation, and Archives each carry
compliance expectations that the OSL usually does not restate.

**Decision:** Move the catalog out of the code and into the database, editable in the
admin-ui.

1. **`ReportKind` becomes an open string** with the built-ins listed in
   `BUILTIN_REPORT_KINDS`. An unknown key gets `GenericReportParser`, which reads the
   workbook as sheets and values like any other; the fixed checks still find the
   built-ins they know by key.
2. **`artifact_types`** holds every input the tool accepts: the OSL, the config, and
   each report. Each carries a label, a description, an optional sample workbook, and
   an `ai_context` field in plain language. A built-in may be switched off but never
   deleted or re-kinded, because the fixed checks look it up by key; an admin-defined
   type may be deleted only while no run has used it, so stored runs keep reading.
3. **`run_scopes`** holds the programmes, with `standing_instructions`. A run records
   its `scope` and a `has_suppressions` answer that defaults to no.
4. **The new-run form is generated** from `GET /runs/options` rather than hardcoded, so
   switching a type off removes its upload slot for every user at once.
5. **Guidance is additive.** `pipeline/guidance.py` builds a short preamble and returns
   an empty string when nothing is configured, so a fresh install sends byte-for-byte
   the prompts it sent before. The preamble labels itself background, not requirement:
   the OSL remains the source of truth (ADR-002), and standing instructions never
   become requirements.
6. **An empty table means "use the defaults", never "accept nothing".** The shipped
   catalog seeds on first read and seeding is idempotent, so an upgrade adds what is
   new without overwriting an administrator's edits.

**Consequences:** A new report type is an admin task, not a release. The preamble is
part of the rendered prompt and therefore part of the cache key (ADR-005), so editing
guidance invalidates exactly the calls it affects and nothing else — no version to
remember to bump. The cost is that a careless administrator can now weaken a prompt;
the 1500-character clip and the "background, not requirement" wording are the guard,
and the golden set is the detector. `report_templates` is replaced by `artifact_types`;
the sample workbook it held is now a field on the type.

## ADR-021 — Learned rules are proposed by the model, approved by a person, and shadowed before they count

**Status:** accepted 2026-09-18 (user decision). The questions this ADR waited on are
answered and recorded in [`phase-6.1.md`](phase-6.1.md) "Decisions"; the ones that
change this ADR are folded into the decision below. One question stays open — whether
a learned rule ever expires — and it does not affect the shape.

**Context:** The tool's rules are fixed at two points today: the checks an
administrator writes by hand, and the reference data they maintain. The people who know
the most about what should be checked are the reviewers, and what they know arrives as
a sentence — "this field is never blank for account review", "this column is what
clause 4.2 is actually asking for". Today that sentence goes in a review note and is
never read again. The request is to capture it, turn it into a rule, and have the tool
get better as it is used.

The risk is equally plain. A sentence typed by a user, passed through a model, becoming
a rule applied to every run, is a path from free text to global policy. Done carelessly
it produces prompt injection with real consequences, a findings list nobody trusts, and
rules nobody can explain.

**Decision:** Build the loop as a state machine with a person at the only gate that
matters.

1. **Observations are anchored, not just written.** A user selects the cell, the OSL
   section, or the config path they mean, and writes their sentence against it. The
   anchor is what makes reliable synthesis possible; prose alone is a guess.
2. **Suggested and active are different states.** `draft → shadow → active → retired`,
   every transition stamped with an actor and a time, nothing automatic. This is what
   every mature data-quality tool does, and the one convention worth copying without
   modification.
3. **The model proposes; code disposes.** Synthesis returns a schema-constrained rule
   object. Code validates it, compiles its expression, resolves its named values
   against the stored samples, and fingerprints it against existing rules for overlap.
   The model has no write, no activation, and no chained execution — its capability is
   "draft a record", which is OWASP's excessive-agency guidance applied literally.
   ADR-001 is unchanged: the model reads meaning, code does every comparison.
4. **The user's words are data.** They reach the prompt inside a delimited block marked
   as a statement to interpret, never as an instruction to follow. The real control is
   not the delimiter, though: it is that nothing the model returns runs until a person
   approves it and a schema has already rejected everything malformed.
5. **Replay before promotion.** A candidate is run against the golden set and recent
   finalized runs, and the administrator sees what would have changed before deciding.
   The golden set already exists for prompt changes; this is the same instrument
   pointed at rule changes.
6. **Shadow before it counts.** An approved rule runs silently until an administrator
   activates it, with its fired count, its dismissal rate, and its shadow findings in
   front of them. Precision is unknown until a rule has met real data, and a
   false-positive flood costs reviewer trust that takes months to earn back. A fixed
   threshold was considered and rejected: a rule that fires rarely would wait forever
   for a sample it never gets, so the judgement is a person's and the evidence is
   shown rather than summarised.
9. **The narrowest scope that fits.** A learned rule applies to the customer or
   programme its observation came from; going global is a separate action. The most
   common cause of a noisy rule is an assumption that holds for most records and not
   all, and widening on evidence is easy where narrowing after the complaints is not.
10. **The author is named and hears back.** Anyone may file an observation, recorded
    against their name, and the outcome comes back to them with the administrator's
    reason. Approval is the real control, so a permission list would guard nothing,
    and a loop that never answers its contributors stops receiving contributions.
11. **No rule expires on its own, and every rule is findable.** One searchable admin
    screen lists every rule whatever its origin, filtered to active by default. An
    administrator enables, disables, or deletes; nothing happens on a timer, because
    a rule that has not fired in a year is either load-bearing or dead and nothing
    inside the system can tell which. Deletion is soft and restorable for six months,
    after which a tombstone remains so findings on old runs still explain themselves.
    Each of these actions asks the administrator to type the word, because a rule
    change reaches every future run.
7. **Provenance is stored, including the diff.** Source observations, model, provider,
   prompt version, approver, timestamp, and what changed between the model's draft and
   the approved rule. The diff is the only measure of how much correcting the model
   needs, and the first place to look when tuning the synthesis prompt.
8. **Learned rules land in the existing tables** — `check_definitions`,
   `compliance_rules`, and the new `field_constraints` — so there is one rule surface,
   one evaluator, and one place to look when a finding is wrong.

**Consequences:** Every learned rule can be explained: who said what, which model drew
which conclusion, who agreed, what it has done since, and who last changed its state.
Because nothing expires, the rule set only grows unless someone tends it, which is why
the noisy-rule and dead-rule reports are part of the same phase rather than a later
nicety. The cost is that nothing is
fast — an observation becomes an enforced rule only after synthesis, approval, replay,
and a shadow period — and that is the correct trade for a rule that touches every
customer's validation. Two counters have to exist from the first day, fired count and
dismissal rate, because alert fatigue is invisible without them and obvious with them.
The audit log and the human-decision record are required artifacts rather than
nice-to-haves, which the NIST AI Risk Management Framework and the EU AI Act's
human-oversight provisions both expect of a system where a model shapes a decision.

## ADR-022 — Login exists, ships off, and there is always a current user

**Status:** accepted 2026-09-18 (user decision); the answers are recorded in
[`phase-6.2.md`](phase-6.2.md) "Decisions". **Amends ADR-008**, which stands as the record of why
v1 shipped without login and why the seam was left in place.

**Context:** ADR-008 chose no login for v1: the tool runs on an internal network, and
the cost of an account system was not worth paying before the product existed. It kept
two provisions — an unused `users` table and one auth dependency every router calls.

Two things changed. In production the organisation needs to know who submitted a run
and who decided a finding, and the config history is the natural place to show it.
More sharply, Phase 6.1 lets a person's sentence become a rule applied to every run,
and a suggestion whose author is unknown cannot be weighed, questioned, or followed up.
Attribution stops being a nicety the moment the tool learns from people.

**Decision:** Add authentication, ship it disabled, and give it one property that keeps
it small.

1. **There is always a current user.** With login off it is a seeded placeholder
   account; with login on it is whoever signed in. No nullable authors, no branch in
   any handler, no code path that exists in only one mode. This is the decision that
   makes the rest of the phase a week rather than a month.
2. **Two independent switches**, `GREENLIGHT_AI_ADMIN_AUTH` and `GREENLIGHT_AI_USER_AUTH`, both
   false by default. Off means no prompt, no cookie, and today's behaviour exactly.
3. **No self-registration.** An administrator creates every account, for both roles,
   capturing a name and an email. Every account sets its own password at first
   sign-in, including the bootstrap administrator.
4. **Accounts are deactivated, never deleted**, so what a person did stays attributed
   to them.
5. **Server-side sessions** in a table, not self-contained tokens, because revoking a
   session and knowing who is signed in both matter more here than saving a read.
   Passwords are `scrypt` hashes with per-user salts from the standard library, which
   adds no dependency.
6. **The training record is append-only.** An observation that has been synthesized is
   marked as synthesized, with the date and the candidate it fed; it is never consumed
   or removed. Rejected candidates keep their sources. Re-synthesis produces a new
   candidate rather than editing an old one.
7. **Sign-in, sign-out, failure, password change, and every account change are audit
   events**, because "who signed in" is the question the phase exists to answer.
8. **The bootstrap password blocks a real deployment.** With admin auth on, the
   default unchanged, and a bind address other than loopback, the API refuses to
   serve. A warning is easy to miss and this is the one credential everybody knows.
9. **Eight hours absolute, one hour idle**, a twelve-character minimum, and lockout
   after repeated failures. No complexity classes and no expiry: both push people
   toward predictable passwords, and current guidance treats forced rotation as
   harmful more often than helpful.

**Consequences:** ADR-008's "no login in v1" becomes "no login by default", and the
provision it kept turns out to have been sufficient: one function body, a session
table, and columns on the tables that record actions. The bootstrap credential is a
real exposure for as long as it stands, which is why the first sign-in forces a change
and the deployment checklist names it; whether the process should refuse to serve while
the default is unchanged is left open deliberately, because it is a policy call rather
than an engineering one. Single sign-on is expected eventually and attaches at the session
table, which records how a session was established rather than assuming a local
password.

## ADR-023 — The admin console overrides the environment, and there is always a layer beneath

**Status:** accepted 2026-09-18 (user decision)

**Context:** Everything about how the tool runs came from `.env`: the model provider
and its key, upload limits, retention, concurrency, and after ADR-022 the login
switches too. Changing any of them meant editing a file on the server and restarting,
which puts every operational decision behind whoever has shell access. The request was
to move those controls into the admin console, keep `.env` working, and have console
values win.

The risk is a configuration system that can break the thing used to configure it. A
console that can change its own database URL, or switch off the login that proves who
is allowed to change settings, is a console that can lock everyone out of the only
tool that could fix it.

**Decision:** A three-layer resolution with a registry, and a short list of things the
console may not touch.

1. **Admin console, then `.env`, then the built-in default.** The table holds
   **overrides only**, so a key nobody has touched behaves exactly as it did when the
   environment was the only source. This is what makes the feature safe to add to a
   running system.
2. **One registry declares every setting**: its type, bounds, default, the environment
   variable it falls back to, its help text, and whether it may be changed at runtime.
   The console renders itself from the registry, so the code and the console cannot
   disagree about what a setting is.
3. **Nothing is read at import time.** A module-level constant is fixed for the life of
   the process, which is the usual reason a runtime setting turns out not to be one.
   Values are resolved where they are used: per request in the API, per job in the
   worker.
4. **Effective immediately, within five seconds.** Each process caches the overrides
   briefly and invalidates its own cache on write, so the administrator sees the
   change at once and the worker picks it up on its next job. Postgres `LISTEN/NOTIFY`
   would make it instant and is not worth an infrastructure dependency for one API and
   a couple of workers; it is the obvious upgrade if that changes.
5. **Some settings are never runtime-editable**: the database URL, the data directory,
   and the bind address. Each is needed to reach or to protect the store itself, and a
   value that gates access to the thing it is stored in cannot live there. They appear
   in the console read-only, with the reason.
6. **The console shows which layer every value came from.** This one detail prevents
   the recurring hour spent wondering why a value differs from `.env`, and it makes an
   accidental override visible and revertable.
7. **Every change is recorded with its previous value** in an append-only log, so
   "put it back" is a button rather than an excavation.
8. **The one secret is encrypted with a master key from the environment**, using
   `MultiFernet` so rotation is adding a key to the front of a list rather than a
   migration written under pressure. **Without a master key the secret is refused
   rather than stored**, and the environment stays the only place it can come from:
   refusing is honest, and storing it in the clear while implying otherwise is not.
   A secret never travels outward — the console learns that one is set and its last
   four characters, which is enough to recognise the right key and useless to anyone
   who intercepts the response.

**Consequences:** Day-to-day operation stops needing shell access. The cost is a second
place a value can come from, which is exactly why the source badge and the change log
are part of the feature rather than a later addition. `.env` remains a complete and
supported way to run the tool, and a deployment that never opens the settings screen
behaves as it always did. The master key becomes something that must be backed up
outside the database from the first day: losing it loses every secret it protects, and
there is no recovery path by design.

## ADR-024 — A configuration note is guidance and an observation at once, never a rule on its own

**Status:** accepted 2026-09-19 (user decision)

**Context:** A reviewer who knows that a particular ETL configuration carries special
rules had nowhere to write that down once. It went into a run's free-text notes and
was gone by the next run of the same configuration. The request was a note tied to
the configuration id, the Solution Canvas config number, that reaches the model on
every future run using it and that an administrator sees as a configuration-specific
comment in the training queue.

**Decision:** One row, two roles, and no new mechanism.

1. **A note is an observation of kind `config_note`** with the configuration it
   follows. It sits in the same table and the same admin queue as every other
   observation, so there is one place an administrator reads what people know.
2. **It reaches the model as background at once**, through the existing guidance
   preamble (ADR-020), labelled as a note on the configuration and never as a
   requirement. It changes what the model pays attention to; it cannot make anything
   pass or fail.
3. **Enforcement goes through the ordinary loop.** If an administrator wants the note
   to become a rule, they synthesize it like any observation and approve the
   candidate, which lands scoped `config:<id>` so it applies to that configuration
   and no other (ADR-021).
4. **It is available whatever Train AI mode says.** The mode gates what the tool
   collects for training; a note is guidance about a configuration, which is useful
   either way. Its field carries no Train AI tag.
5. **Anyone may write one**, under their name. Edits keep the earlier wording, and a
   note is switched off rather than deleted, for the same reason nothing else in the
   training record is deleted.
6. **A run keeps a copy of the notes in force when it was submitted**, and the frozen
   report shows them. A reviewer reading a finding needs to know what context the
   model was given, and that must not change after the fact.

**Consequences:** No second table, no second queue, no second prompt path. The cost is
that a note applies without review, which is acceptable precisely because it cannot
enforce anything; the moment it should, a person is in the loop. The rule scope
vocabulary grows by one form, `config:<id>`, beside `all`, a customer name, and
`programme:CODE`.


## ADR-025 — The product is Greenlight AI

**Status:** accepted 2026-09-19 (user decision)

**Context:** The tool was built under the working name vigilAI. Before it reaches the
delivery teams it takes its product name, Greenlight AI, with the tagline *Nothing
ships without a green light.* Behaviour does not change; the name does, everywhere a
person or a machine reads it.

**Decision:** One rename, applied in every casing at once, with no compatibility layer.

- Display **Greenlight AI**; kebab `greenlight-ai` for packages, folders, images, and
  file names; snake `greenlight_ai` for the Python package, database objects, and the
  Postgres role and database; `GREENLIGHT_AI_` for every environment variable and
  constant; `greenlight` where a single word is needed, such as the container user.
- **Persistent identifiers were renamed too**: the compose project (so its volumes are
  `greenlight-ai_pgdata` and `greenlight-ai_files`), the Postgres defaults, and the
  SQLite default `data/greenlight-ai.db`. Nothing had shipped, so the old local
  volumes and files are left behind rather than migrated.
- **The old environment names stopped working.** A hard cutover was chosen over a
  shim that reads both, because there was nobody to protect and a shim has to be
  removed later.
- **The session cookie is `greenlight_ai_session`**, which signed every session out
  once.
- **Applied migrations keep their revision ids and DDL.** Only the module path of the
  custom column type they import changed, which is required for them to load at all.
- **History was rewritten** at the user's direction: ADR bodies, session-log entries,
  and checked criteria read the new name. This ADR is the record that the name was
  once different.
- **The mark** is a green light in the brand box; there was never a logo image. The
  wordmark is text.

**Consequences:** The GitHub repository and the git remote still carry the old name
until the user renames them, and two documentation URLs point at the current
repository until then. Anyone with a local `.env` or shell exports under the old
prefix must update them. `compare-file` references are untouched: that is a sibling
project, not this one.

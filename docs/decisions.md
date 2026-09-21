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
   shown rather than summarised. *Amended 2026-09-20:* "in front of them" was a
   promise without a screen until Phase 6.13b. The shadow findings are now listed per
   rule on the administrator's Rules screen with a dismissal control; that is what the
   dismissal rate is made of, and reviewers never see them (ADR-040).
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

## ADR-026 — Programme rules are read by the model and graded by code

**Status:** accepted 2026-09-19 (user decision)

**Context:** A delivery programme, Account Solicitation, Account Monitoring, Archives,
carries expectations the OSL does not restate, and until now the tool held them as
one free-text "standing instructions" field that reached the model as background and
could never produce a finding. The request was rules of the programme's own, several
per programme, each with its own strictness, so a breach is surfaced with the
seriousness the administrator intended. And a first, simple check that a run declared
as a programme actually is one.

**Decision:**

1. **A programme rule is a sentence with a strictness**: must, should, or advisory.
   Several per programme, edited in the console, with the same lifecycle as every
   other rule.
2. **The model reads; code grades.** One call per run shows the model the rules and
   what the delivery contains, and it names which rules the evidence breaks, quoting
   it. The finding's severity comes from the rule's strictness, applied by code:
   high, medium, low. The model is told not to decide seriousness and not to compare
   numbers. A rule id it was never shown is discarded as invention; a low-confidence
   breach is a review item.
3. **The programme check is a grep.** Each programme carries admin-editable keywords.
   The check scans the OSL, the configuration, and the report headers. Declared
   programme absent and another clearly present is a high finding naming both; absent
   with nothing else is a review item. The run continues either way: a keyword check
   is not reliable enough to stand in someone's way, and the finding puts the question
   in front of the reviewer before the programme rules are trusted.
4. **Programme rules are a fourth rule kind** on the Rules screen, so there is still
   one place to look when a finding surprises someone.

**Consequences:** The standing-instructions field stays as background; the rules are
where enforcement lives. An administrator can now express "this always matters" and
"this is worth a glance" without a developer. The cost is one more model call per
run, cached like every other, and the discipline that the model is never allowed to
grade, which the prompt tests enforce.

## ADR-027 — A run has its own identity; the configuration id is information; the credit date is checked

**Status:** accepted 2026-09-19 (user decision)

**Context:** The new-run form treated the configuration id as the run's key, and the
"run date" was the submission date, which the tool already records as `created_at`.
What a reviewer needs on the run is the **credit date**, the as-of date of the credit
data in the delivery, and that date is worth checking: a report that does not carry
it is a report that cannot be tied to its delivery.

**Decision:**

1. **Every run has its own id.** The configuration id is entered for information,
   is optional, and may repeat across runs. Configuration notes still attach to it.
2. **The run carries a credit date**, entered on the form. Code searches the OSL,
   the configuration, and every report for the date in its common spellings and
   raises `credit_date_missing`: medium when it appears nowhere, low when it appears
   only in the OSL or the configuration and not in the reports.
3. **Every form and console field says whether the model sees it.** Customer, order,
   configuration id, and additional notes never reach the model. The programme and
   its rules, the suppressions answer, configuration notes, and delivery notes do,
   as background (ADR-020). Keywords, checks, and compliance rules are evaluated by
   code and never sent. The hint under the fields that reach the model says that
   accurate notes improve the validation.
4. The deliverable count and outputs-covered fields are removed from the form; the
   files themselves say what arrived.

**Consequences:** Migration `b614b77ca9d8` renames the column. A run that repeats a
configuration id is normal, which is what the delivery-drift comparison of a later
phase will build on.

## ADR-028 — Prompts are hardened for a real model; the real benchmark waits for the target environment

**Status:** accepted 2026-09-19 (user decision)

**Context:** The first run of the golden set against a real model (a small hosted
one, comparable to a mid-size local model) scored 0 / 12: every case failed at stage
2 because the model returned keys the schema forbids (`fields` for the delivered
attributes, `field_name` on the requirement rather than in a condition, a
`description`, invented requirement types). With that fixed, two disagreements
between how the stand-in and a real model read the fixtures produced spurious
findings: the input population size was extracted as a delivery quantity, and
suppression flags and pipeline steps were described as technical plumbing.

**Decision:**

1. **Stages 2 and 3 fold the model's answer onto the schema before validating it**
   (`normalize_response`, `normalize_elements`): synonyms are renamed, a flat
   `field_name` becomes a condition, unknown requirement types and operators are
   folded onto the closed sets with a logged count, unknown keys are dropped, and
   booleans become the strings the prompts ask for. Renaming and dropping only; no
   value is compared or computed (ADR-001).
2. **The prompts name the exact keys** and say no other key is permitted, with worked
   examples for the shapes the model got wrong. `s2_extract` is version 3,
   `s3_describe` version 2, so every cached answer is refreshed (ADR-005).
3. **Both prompts read exclusions the same way.** An exclusion of records that carry
   a flag or appear on a list is criteria on that flag (`= "true"`, action reject);
   value_set is for a listed set of an attribute's values. A list of processing steps
   is a waterfall; a record count is a quantity; the input population is context, not
   a requirement.
4. **Further model benchmarking stops here.** The synthetic set is now clean on one
   real model (`docs/benchmarks/phase-2-real-model.md`). Comparing larger models on
   synthetic fixtures would measure the fixtures, not the product. The benchmark that
   counts runs on the target environment, against the in-house gateway, on real OSLs
   and reports, and is the first task when that environment exists (Phase 7).

**Consequences:** The pipeline no longer breaks on a well-meaning answer in a slightly
different shape. The stand-in is unchanged and still passes. The Anthropic key used
for the run lives only in `.env` and should be rotated.

## ADR-029 — Scope is one token; guides are additive; a version is a snapshot and a revert is a new version

**Status:** accepted 2026-09-19 (user decisions, Phase 6.8)

**Context:** A compliance rule or check applied everywhere or to one customer, never
to one delivery programme. An artifact type carried a paragraph of guidance and up
to three samples, with no structured way to say what a report cell means and where
it answers to. And nothing an administrator edits kept its history.

**Decision:**

1. **Scope is one stored token**: `all`, a customer name, or `programme:CODE`. Code
   decides scope with no lookup (`checks/definitions.in_scope`). A programme scope
   matches only a run of that programme; a run with no programme sees global and
   customer rules only. The Rules, Checks and Compliance screens read the token as
   words.
2. **A validation guide is additive.** Entries reach the model as background, never
   as a precondition (ADR-020). An entry with a resolvable locator and a config path
   becomes a check automatically, **born in shadow** (ADR-021), activated from the
   Rules screen when the numbers say so. An OSL reference is a section number and a
   phrase, either optional.
3. **A version is a snapshot; a revert is a new version.** Artifact types with their
   samples and guide, and a programme's rule set, are snapshotted on every save. Ten
   are listed; a version a run inside the retention window still references is kept
   beyond the ten. Reverting writes the snapshot back as the next version, so nothing
   is ever lost, and is audited with the typed word.

**Consequences:** The pipeline's scope check is a pure function with a test per
form. A guide can be written entirely from the sample preview. The definitions an
administrator edits are as safe to change as the configurations already were.
Proving the compiled check exposed that a shadow check never ran and that shadow
findings were visible everywhere; both are fixed, so ADR-021 now holds for checks
as it did for learned rules.

## ADR-030 — Delivery drift is computed in code from the previous finalized run of the same configuration

**Status:** accepted 2026-09-19 (answers a design-doc open question)

**Context:** A reviewer's first question on a repeat delivery is "what is different
from last time", and the tool could not answer it although every run stores its
findings, its requirements, and its configuration.

**Decision:** The previous run is the latest **finalized** run of the same
configuration id for the same customer submitted before this one; finalized because
its decisions are frozen, and a comparison against a run still under review would
move. Four comparisons, all in code: findings new and resolved (matched on type,
leg and title), the previous run's Not OK findings that are back, requirements whose
value changed (matched on type and OSL reference, not on their number), and the
configuration diffed by JSON path. Shown on the review screen and frozen into the
report at finalize. A run with no configuration id has nothing to compare with, and
says so.

**Consequences:** No new tables and no model call. The comparison is only as stable
as finding titles are, which is why titles are generated by code and never by the
model. A rerun of identical inputs compares with its own predecessor like any other
run, which is exactly what a "did the fix land" check wants.

## ADR-031 — Who decides the theme: the lock, then the person, then the deployment

**Status:** accepted 2026-09-19 (Phase 6.6)

**Context:** Four palettes existed, chosen by one `.env` variable at request time.
The user wanted to step through them on the real screens, and an administrator's
say over what every user sees.

**Decision:** Three layers, narrowest first. The administrator's **lock**
(`ui.theme_locked`): when on, the default applies to every browser and the picker is
hidden. The person's **own choice**, remembered per browser. The deployment's
**default** (`ui.theme`): console over `GREENLIGHT_AI_UI_THEME` over the brand
palette (ADR-023). Both settings are read by anyone through `GET /appearance`, with
no login, because a browser must know its colours before it knows its user, and the
answer carries nothing else. The server renders the default so the first paint is
right; the browser applies its own choice on mount and re-reads the appearance every
minute and on return to the tab. Every palette is checked by a test against the same
contrast thresholds, so a look can never flatten a severity.

**Consequences:** No redeploy for a new default or a lock. A palette is one block of
tokens in each app's `globals.css`, one entry in `lib/theme.ts`, and one choice in the
registry; the contrast test fails the moment the tokens are wrong.

## ADR-032 — A delete is typed on the admin side, confirmed on the user side, and one word covers a batch

**Status:** accepted 2026-09-19 (user decision)

**Context:** Seven admin deletes fired on one click; compliance rules could not be
edited; long lists had no way to act on many rows at once.

**Decision:**

1. **Every admin delete asks the person to type `delete`**, and the API refuses a
   delete without `?confirm=delete`, so a script cannot skip the pause the screen
   imposes. Checks and compliance rules are soft-deleted through the rule lifecycle
   and stay restorable; the reference lists are removed outright.
2. **The user console asks "are you sure" and never a word.** It has no delete
   today; the shared dialog exists so the first one has nothing to invent.
3. **A batch takes one typed word**: `delete` for deletes, the action for state
   changes (`disable`, `activate`, …), audited as counts.
4. **Every rule's wording is editable on its owning screen**; the Rules screen
   links there. An edit bumps the rule's version so old findings keep theirs.

**Consequences:** One component (`confirm-delete`) and one bar (`bulk-bar`) in the
admin app; every delete route carries the same dependency; a compliance rule now has
a version like a check.

## ADR-033 — Meaning: the model proposes a requirement's links, a person confirms, code compiles

**Status:** accepted 2026-09-20 (Phase 6.10)

**Context:** The tool could say what a report cell means (guides) but nothing pointed
from an OSL requirement to the configuration block that implements it and the report
cells that evidence it; OSLs vary a little by programme and there was one unscoped
OSL type.

**Decision:**

1. **Samples belong to a programme or are global**, three per type per programme. A
   programme reads its own samples where it has any, else the global ones.
2. **A meaning entry** is one requirement's links: OSL section, configuration path,
   report cells, what to validate, a comparison, the model's question and the
   administrator's note. Global entries apply to every run; a programme's entries add
   to them and a same-key entry overrides the global one.
3. **The interview** is one cached model call per OSL section with the section text,
   the configuration blocks, and the report cells as labels only. The model proposes
   links and asks when it cannot place one; it never compares (ADR-001). Proposals
   land as rows: *proposed*, or *open* with the question.
4. **Confirming compiles.** A confirmed entry with a configuration path, a report cell
   that resolves on a sample, and a comparison becomes named values and a check born
   in shadow (ADR-021), scoped `programme:CODE` or `all`; a confirmed compliance
   suggestion becomes a shadow compliance rule. Rejecting retires both. Every change
   is a version of the scope's meaning (ADR-029).
5. **Cell-level meaning stays on the artifact type** (the guide); Meaning shows it as
   a second tab rather than duplicating its storage.

**Consequences:** An administrator defines what a delivery means once per programme
from real samples, on the target machine, without a developer. The model's role is
bounded to reading; nothing counts until a person confirms and then activates.

## ADR-034 — Several lenses read a finding independently; code merges them, and no lens grades

**Status:** accepted 2026-09-20 (user decision, Phase 6.11e)

**Context:** The question put to this phase was whether two or three agents with
different roles, given the same submission, should discuss it for a few rounds before
the tool answers. The instinct behind it is right: different lenses catch different
classes of error. A delivery lead reads a report asking whether the output matches what
was configured; a compliance officer asks which obligation a discrepancy touches; the
requirements owner asks whether this is what the specification asked for. One prompt
cannot hold all three stances at once, and stage 8's single second opinion has held one.

**Decision:** Build the lenses. Leave out the conversation.

1. **Independent readers, merged by code.** Each lens receives the finding and its
   evidence and nothing else, answers the same schema, and never sees another lens's
   answer. Code merges: every answering lens agrees and the finding is verified at the
   lowest confidence offered; any disagreement downgrades it to `review` with each
   dissenting lens's reason attached. This is sectioning, not debate.
2. **No debate, for four reasons that hold here specifically.** *Cost*: three agents
   over three rounds is up to nine times the calls at that stage, on an in-house 20–40B
   model where a run already takes five to fifteen minutes, and the cache stops helping
   because each round's input contains the last round's output. *Convergence*: agents
   that see each other's answers drift toward the most confident one, which removes the
   independence that made a second reader worth having; published debate results show
   modest gains on open reasoning and almost none where the truth is deterministic.
   *Auditability*: a QC record must say "this finding exists because rule X, evidence
   Y", and "three personas argued for two rounds" is neither reproducible nor
   defensible to an auditor. *Authority*: the model may not compare or grade (ADR-001,
   ADR-026), so the only thing the agents could debate is meaning, which stages 2, 3, 4
   and 8 already isolate into narrow schema-bound questions.
3. **A lens changes confidence, never severity.** It can send a finding to a person and
   it can raise a question from the same evidence, which becomes a `review` item. It
   cannot make anything more serious, and it cannot delete anything. The severities
   code set stand.
4. **A lens that does not answer counts as neither.** Two lenses that agree still
   verify. No lens answering leaves the finding exactly as the checks produced it, and
   the run says so as a notice rather than passing over it.
5. **The same question asked once.** One lens reads every high-severity finding, so the
   same observation arrives several times; a reviewer needs it once with the readings
   that raised it named. A proposal repeated five times is five times the noise.
6. **Switchable, capped, and measured before it is the default.** `LLM_VERIFY_LENSES`
   stays at `single` — today's behaviour, call for call — until the golden-set
   benchmark compares the three against it. What reviewers see changes on evidence, not
   on argument. A per-run call cap sits beside the token budget, and empty turns
   verification off, which the run reports.
7. **The same discipline, twice more, off the run path.** A coverage reader labels the
   requirements code found unevidenced (Phase 6.11f), proposing only. A critique pass
   reads a drafted rule back against the statements it came from and allows one redraft
   (Phase 6.11g), once per candidate at authoring time.

**Consequences:** Each lens's answer is cached under its own key, so a re-run costs
nothing and the record of what each said is complete and replayable. Verification costs
three calls per high-severity finding when the lenses are on, which is the reason for
the cap and the reason the default waits for a measurement. The alternative — one
prompt asked to hold three stances — was rejected because a prompt that asks for
everything reliably returns the average.

## ADR-035 — The finalize gate fails closed, and freezing carries an attestation

**Status:** accepted 2026-09-20 (user decision, Phase 6.11d). Amends ADR-015.

**Context:** ADR-015 set the gate at "every high-severity finding has a decision". That
reads the absence of a finding as a pass. It says nothing about a `review`-severity
finding, which is precisely the one the model was unsure about; nothing about a
requirement no report could evidence; nothing about a check that was defined and could
not be evaluated; and nothing about a verification that failed and was logged. A
reviewer who opens a run with three findings, decides them, and freezes the report has
no way to learn that nine requirements were never compared against anything. That is how
a compliance error leaves the tool as a clean report.

**Decision:**

1. **Coverage is a first-class output.** After stage 7, code records one state per
   requirement — checked, traced but unchecked, untraced, verified by hand — with the
   reason, and how many checks touched each uploaded report. Pure code, no model
   (ADR-001). It is stored on the run, shown on the review screen and in the frozen
   report, and given to the summary prompt as counts so the summary cannot call a
   delivery clean when part of it was never examined.
2. **The gate widens.** Every high **and** every `review` finding needs a decision, and
   every requirement no report evidenced and every check that could not be evaluated
   needs an **acknowledgement**. An acknowledgement is not a decision that the delivery
   is fine; it is the record that the gap was in front of somebody before the report was
   frozen. An untraced requirement needs none: it is already a high-severity finding.
3. **The gate is one implementation.** `api/gate.py` answers both "can this be frozen"
   for the screen and "may this be frozen" at finalize, so what a reviewer is shown and
   what the API enforces cannot drift apart. Refused with 409, not merely greyed out.
4. **Freezing asks once, with the numbers.** The confirmation carries the coverage
   counts, the gaps acknowledged, the checks that could not be evaluated, the shadow
   rules and definition versions in force, and the run's notices. The same block is
   stored on the final report and rendered in it, because a report that is evidence of a
   review should say what the reviewer was shown.
5. **A run from before coverage existed is unaffected.** An empty coverage column reads
   as nothing to acknowledge, so an old run's gate is exactly what it was.

**Consequences:** Some runs that would have been frozen in three clicks now need a
person to look at what was never checked, which is the point and is the cost. The
attestation makes the frozen report meaningfully stronger evidence: it states the
limits of what was verified rather than implying there were none. Two fixtures showed
the hole while this was built — every synthetic case, the clean baseline included,
carries two checks that could not be evaluated and used to pass through undecided.

## ADR-036 — A second approver is a programme's choice, and stands down when login is off

**Status:** accepted 2026-09-20. Deferred from Phase 6.11 and built after it.

**Context:** ADR-035 made the finalize gate fail closed, but every decision on it is
still one person's. Some findings are not: a breach of a rule a programme calls `must`,
and a compliance rule the configuration does not implement, are things a programme
decided in advance that nobody waves through alone. The question was whether to build
four-eyes at all, and if so how narrow to make it.

**Decision:**

1. **The programme decides, not the product.** A delivery programme carries a
   `second_approver` switch, off by default. Programmes differ in how much a waved-through
   compliance finding costs, and a global rule would be wrong for most of them.
2. **Only what was waved through.** The rule triggers on a `programme_rule_violation`
   or a `rule_missing_in_config` the reviewer marked **OK** — false positive or accepted
   risk. Deciding one Not OK is the delivery being corrected, which needs no second
   signature. Seriousness alone is not the trigger; waving it through is.
3. **A signature, not a re-review.** The second person is not asked to redo the review.
   They are shown what was waved through and they sign that the run can be frozen. That
   is the whole of what this control asserts, and claiming more of it would be a lie
   about what actually happened.
4. **From someone else.** The approver must be a different account from the reviewer
   who made those decisions, refused with a 422 otherwise. A signature from the person
   who made the decision is not a second pair of eyes.
5. **Inert while login is off.** With login off every action belongs to the same
   placeholder account (ADR-022), so a second approver would be the same person and the
   gate could never be passed: every affected run would be unfinalizable forever. The
   rule therefore stands down entirely rather than deadlocking. **A gate nobody can
   pass is worse than no gate** — it teaches people to look for a way round, and the way
   round is usually turning the whole thing off. The admin console says this beside the
   switch, and the deployment checklist says it beside login.
6. **The gate reads the settings the app is running with**, passed in rather than
   re-read from the environment. An app built with login on must not be told it is off.
7. **It reaches the frozen report.** The attestation records who approved, when, what
   they covered and any note, because a report that is evidence of a review should say
   whose approval it carries.

**Consequences:** A programme that switches this on and runs without login gets nothing,
silently in the gate and loudly in the console. That asymmetry is deliberate: the
failure mode of a control that cannot be satisfied is worse than the failure mode of one
that is absent, and the honest place to say so is where somebody is deciding. The
control is narrow enough to be true — one signature, from someone else, over a named
list — and nothing about it implies the second person re-derived the first's work.

## ADR-037 — One module reads a scope, and the stored columns are left alone

**Date:** 2026-09-20 · **Status:** accepted · **Phase:** 6.12a

**Context:** A check, a compliance rule, a field constraint, a programme rule and a
learned rule all carry a scope. Four shapes had been stored over the product's life —
`all`, a bare customer name, `programme:CODE` (Phase 6.8) and `config:ID` (ADR-024) —
and each reader interpreted the string for itself. The pipeline's `in_scope` knew three
of them, the field-constraint loader knew a different three, and the two consoles knew a
fourth set between them. A scope was therefore capable of meaning one thing on the
screen that defined it and another in the run that used it, which is the failure this
product exists to prevent, happening inside the product.

There were two obvious answers: rewrite the columns into one form, or leave them and
unify the reading.

**Decision:**

1. **One module interprets a scope string**, `greenlight_ai/scopes.py`, with a `Scope`
   value object, a `parse` that accepts every form ever stored, a `token` that renders
   the canonical one, and a `covers` that answers the only question anyone asks. Nothing
   else parses a scope. `checks.definitions.in_scope` survives as the name the pipeline
   calls and decides nothing itself.
2. **No data migration.** Rewriting three columns across a dozen tables would be the
   riskiest change in the product for a cosmetic gain, and a half-completed rewrite
   would leave exactly the ambiguity it was meant to remove. A row becomes canonical the
   next time somebody saves it, and reads identically until then. The older forms parse
   forever; that is the contract, not a transitional courtesy.
3. **The wire is where the vocabulary is unified.** One pydantic type canonicalises a
   scope in both directions, so any form is accepted on input and the canonical token is
   what goes back out. The consoles never learn that four shapes exist.
4. **The canonical token is `everywhere`, `programme:CODE`, `customer:NAME` or
   `config:ID`.** `all` became `everywhere` because `all` already means something else
   in the rule schema (`applies_to: all`, meaning every record rather than every run),
   and a bare customer name gained a prefix because it was the one form indistinguishable
   from a typo.
5. **A scope that names nothing covers nothing.** `programme:` with no code, or a
   customer scope with no name, matches no run. A half-written row must not quietly
   become a rule that runs everywhere, and the console refuses to save one.
6. **A configuration scope is not picked, it is inherited.** It comes from a note
   written against one configuration (ADR-024); the scope control shows it rather than
   turning it into a customer name.

**Consequences:** A programme-scoped field constraint now actually reaches the pipeline.
It did not before: the loader compared the stored string against `all`, the customer name
and `config:ID`, so a rule scoped to a delivery programme was loaded and never matched.
Found by making one module answer the question. The cost is that two files, one Python
and one TypeScript, must agree on the vocabulary; both say so at the top, and both are
tested against the same list of stored forms.

## ADR-039 — A judgment check shows the model named values and an instruction, and code sets the severity

**Date:** 2026-09-20 · **Status:** accepted · **Phase:** 6.13c

**Context:** The design has always allowed a second kind of administrator check, for a
rule a formula cannot express: *the billed volume should be in line with the delivered
volume*. The console could define one, the database stored it, the loader scoped it, and
stage 7 skipped it with a log line. It was the one place the product lets the model
judge values rather than read text, and ADR-001 says code does every comparison, so the
question was whether to remove it or to finish it in a way that keeps that rule.

**Decision:** Finish it, narrowly.

1. **The model sees the administrator's instruction and the named values the
   administrator listed, and nothing else.** A judgment check carries `value_names`; a
   check that names none is refused at save. Stage 7 resolves only those values and
   renders `name = value` lines. No sheet, no row, no report reaches the prompt. An
   unresolved value is a `could_not_evaluate` finding, as it is for an expression check,
   and the model is not asked.
2. **The model answers pass, fail or review with a reason and a confidence; code decides
   what each becomes.** `fail` is a `judgment_failed` finding at the severity the
   administrator set on the check. `review`, or a `fail` below a fixed confidence floor,
   is a review-severity item that says a person must judge. `pass` records nothing. The
   model never sets a severity and never sees the check's.
3. **Silence is not a pass.** A model that does not answer leaves a run notice naming the
   check. A check that quietly recorded nothing on an error would be the one thing a
   check must not do.
4. **It is a model call like every other.** It goes through the one adapter, is cached on
   the rendered prompt and the prompt version, counts toward the run's token budget, and
   coverage records the reports the values came from. A judgment check in shadow produces
   a hidden finding, so its precision is measured the same way as any learned rule.
5. **Use sparingly stays.** The console says what the check costs: one model call per run
   it is in scope for.

**Consequences:** ADR-001 holds. The model reads the values and the sentence and
expresses a reading; it computes nothing, and the values it reads were resolved by the
same code that resolves them for an expression check. The evidence on a judgment finding
is the rendered lines, so a reviewer sees exactly what the model saw. The cost is one
call per check per run, which is why the check requires the administrator to say which
values it needs rather than offering every named value.

## ADR-040 — Shadow findings are visible to administrators only, and dismissible

**Date:** 2026-09-20 · **Status:** accepted · **Phase:** 6.13b

**Context:** ADR-021 says an approved rule runs in shadow until an administrator
activates it "with its fired count, its dismissal rate, and its shadow findings in front
of them". Until Phase 6.13b the findings were stored with `shadow = true`, hidden from
every list, and shown to nobody; the dismissal rate was always zero because nothing could
be dismissed. Precision in shadow was a promise, not a measurement.

Two audiences could have seen them: the reviewers who judge findings on a run, or the
administrators who decide whether a rule goes live.

**Decision:**

1. **Reviewers never see a shadow finding.** They carry the review load already, and a
   rule in shadow is by definition one nobody has yet trusted. The review screen names a
   shadow rule as *running silently* under *Rules applied to this run*, and shows nothing
   of what it found.
2. **Administrators see them per rule** on the Rules screen: the most recent findings a
   shadow rule produced, each with the run it came from and a *Not a real problem*
   control. That control records `review_status = false_positive` on the finding, through
   the same endpoint a reviewer's decision uses.
3. **The dismissal rate is made of those decisions.** The Rules screen's fired and
   dismissed counts come from the finding rows, so a rule's precision in shadow is the
   fraction an administrator judged wrong. There is still no threshold; the numbers are
   shown and a person decides (ADR-021, item 6).
4. **A finding says where it came from.** Every finding carries an origin (built-in,
   administrator, guide, meaning, learned) and a one-line summary of the rule behind it,
   resolved from its `rule_ref` at read time. A reviewer who sees a finding from a
   learned rule sees that it was learned. An observation's outcome (waiting, drafted,
   approved, live, disabled, rejected) is derived the same way, from the candidate and the
   rule's current state, so it cannot go stale.

**Consequences:** "Shadow before it counts" now has the evidence it always claimed. The
cost is one more list on the Rules screen and one more flag on the finding endpoint. A
shadow finding dismissed by an administrator is a finding row like any other, so it
survives the rule's activation and stays in the record.

## ADR-038 — An administrator's examples show the model a shape, and are never rules

**Date:** 2026-09-20 · **Status:** accepted · **Phase:** 6.13d

**Context:** Every prompt ships with worked examples written in Python, and they are
what makes a mid-size model reliable on a narrow task. An administrator could teach the
model a great deal — background prose per programme and per artifact, the validation
guides, the meaning map — and could not add a single worked example: not one *this
wording means this requirement* pair drawn from the deliveries they actually see. The
one thing that most improves how a model reads their documents was the one thing only a
developer could change.

The risk in letting an administrator write into a prompt is obvious: a sentence in an
example can read as an instruction, and a model told to do something else stops doing
the job. The decision is about what makes that safe rather than whether to allow it.

**Decision:**

1. **An example is a pair, not a sentence.** It names a stage, what the model would be
   shown, and a good answer. There is no free-text field that reaches a prompt. The
   block is rendered under one line saying the examples show the shape of a good answer
   and are not rules.
2. **The answer is validated against the stage's own schema before it is stored**, which
   is the same check the prompt suite applies to the built-in examples. An example the
   schema would reject teaches a shape the pipeline then refuses to parse, so it is
   refused at the console with the field named rather than discovered at run time.
3. **The built-ins stay as the floor.** The library is added after them, numbered on
   from them, and never replaces one. A stage with no library examples renders exactly
   as it always did.
4. **At most four per stage, narrowest scope first**, and the console refuses to store a
   fifth *active* one. A cap that silently dropped the fifth would leave a row that looks
   live and reaches nothing, which is the class of defect this phase exists to remove.
   Scope is the one vocabulary (ADR-037), so an example can belong to one programme,
   one customer, one configuration, or everywhere.
5. **Examples are inserted into the rendered prompt, never substituted into it.** What
   an administrator wrote is never read as a template placeholder, and because the text
   is part of what is hashed, adding an example refreshes exactly the calls it changes
   and nothing else (ADR-005). No separate cache-key field was needed.
6. **The personal-data tripwire runs on save.** An example is text somebody pasted from
   a real delivery, and save is the last moment the person who pasted it can take it
   out (ADR-003).
7. **Promotion needs a person's click.** The three places somebody has already corrected
   the model — a confirmed requirement mapping, a requirement a reviewer rewrote, an
   approved candidate — each offer a *Use as example* control, and each stored example
   records where it came from. Nothing is promoted automatically: a correction is
   evidence that one reading was wrong, not evidence that it generalises.
8. **Examples are versioned like every other definition** (ADR-029), per stage, with the
   same ten-deep list and revert.

**Consequences:** The tool can now be taught to read a customer's documents the way
their people read them, by the people who know. What it cannot be taught this way is a
rule: ADR-001 is untouched, an example changes only how the model reads, and every
comparison is still made by code against a rule in the rule tables. The cost is a
prompt that grows by up to four examples per stage, which the cap bounds, and one more
thing to keep true: a library example that stops matching the deliveries is as
misleading as a stale document, which is why each one records why it is there.


---

## ADR-041 — The artifacts are checked against each other before the model runs, anyone may accept a mismatch, and acceptance does not block finalize

**Status:** accepted 2026-09-20 (user decision, before Phase 6.14 was built)

**Context:** The tool validates a delivery thoroughly and says nothing about whether the
delivery is the one the submitter claims. A run submitted on 2026-09-20 with the wrong
customer, the wrong configuration id and a credit date present in none of the artifacts
finished `needs_review` with four ordinary findings and a confident summary. The evidence
was there and parsed — `config.json` declares both `configuration_id` and `customer` —
and neither was ever compared with what the submitter typed. Delivery drift (ADR-026)
then reported "no earlier finalized run of configuration CFG-DOES-NOT-EXIST-999", which
a reviewer cannot tell apart from a legitimate first run: a mistyped configuration id silently
disables the drift comparison and looks correct doing it.

The one such check that existed, the credit date, ran at stage 7 of 9 and searched
for the date's *value* in every cell, so it could report absence but never a mismatch,
and any coincidental occurrence passed it.

**Decision:**

1. **A mismatch is a gate, not a finding.** Code compares the submitted configuration id,
   customer and credit date against what the artifacts declare, synchronously at submit,
   after the files are stored and **before any model call**. A finding is something a
   reviewer weighs against other findings; an artifact mismatch says the other findings
   may have been computed against the wrong premise, so it belongs in front of them. The
   comparison is code on parsed input — no model reads it (ADR-001) — and stage 1 parses
   a whole run in tens of milliseconds, so the gate costs nothing.
2. **A mismatch holds the run; nothing is re-uploaded.** The run and its files exist
   before the gate runs, which is what makes acceptance possible without resubmitting.
   A run with no mismatch is queued exactly as it is today.
3. **Anyone who can submit a run may accept a mismatch, with a reason per mismatch.**
   No role, no routing, no second person. The check earns its place by putting the
   disagreement in front of whoever is standing there; the record of who accepted and
   why is what makes it reviewable afterwards. Who *ought* to be consulted before
   accepting is a delivery-process question and belongs in `docs/gd-rollout-plan.md`,
   not in an authorization check in the tool. Building it as a role would also make the
   tool behave differently depending on whether login is switched on, which ADR-022
   exists to prevent.
4. **The gate does not cross-check run history.** A configuration id that is valid but
   has only ever belonged to a different customer is a real mis-submission shape, and it
   is deliberately out of scope: it needs a second source of truth, it is wrong for
   legitimate reasons (a customer renamed, a configuration transferred), and comparing
   against the artifacts catches the common case. Revisit only with evidence that the
   common case was not enough.
5. **Acceptance does not block the finalize gate.** It is recorded, it appears on the
   review screen and on the frozen report with who accepted and why, and the reviewer
   weighs it like anything else they are shown. **This departs from ADR-035**, which made
   a coverage gap block finalize until acknowledged, and the difference is deliberate: a
   coverage gap is a question the tool cannot answer and must put to a person at the last
   possible moment, whereas an artifact mismatch is a question that was already asked and
   answered by a named administrator before the run was allowed to start. Asking twice
   would train people to click through both. One acceptance, at the point the question
   arises; the report carries it forward.
6. **The credit date is resolved by label, then compared by value.** What a delivery
   calls it varies — *as-of date*, *data date*, *cycle date*, *extract date* — so the
   labels are scoped data using the one scope vocabulary (ADR-029), in their own table.
   They are not `attribute_aliases`: those resolve *data attribute* names and load as
   global-plus-customer only, the one table in the product that never adopted the scope
   vocabulary, and overloading it would repeat the near-miss ADR-029 exists to prevent.
   The check finds the labelled cell and compares its value, so it can report a mismatch
   rather than only an absence; where no labelled cell is found it falls back to the old
   search and says that it did.

**Consequences:** A wrong-artifact submission is stopped before it costs a model call,
and the reviewer of an accepted one can see that somebody waived the question. The cost
is a new run state (`held`) that every queue consumer and every screen listing runs has
to know about, and one more question a submitter can be asked at submit time. The
gate is code-only and adds no prompt, so the golden set is unaffected. What this does not
do is verify that a configuration *belongs* to a customer — only that the artifacts agree
with each other and with what was typed; point 4 is the reason, and it is revisitable.

## ADR-042 — A programme keyword is matched loosely and counted strictly

**Status:** accepted 2026-09-20 (Phase 6.17a).

**Context:** The programme classification check greps a delivery's OSL, configuration
and report headers for a programme's keywords and reports `programme_mismatch` when
none of the declared programme's words appear. It was the third surface measured for
the brittleness [`phase-6.15.md`](phase-6.15.md) found in compliance rules and
[`phase-6.16.md`](phase-6.16.md) 6.16d found in named values, and it failed worse than
either: compliance rules were repaired, named values were left alone because they fail
at review severity, and this one fails at high.

Twenty deliveries, every one genuinely the programme it declared, worded the way
another customer might word it: 4 were silent, 11 raised a review item, and **5 fired
at high severity**. Two defects compounded.

1. A phrase keyword needed exact adjacency and exact plurality. `existing accounts` did
   not find `existing account`; `invitation to apply` did not find
   `invitation-to-apply`; `portfolio review` did not find *ongoing review of the
   portfolio*. Single-word keywords survived inflection for free, because a substring
   test catches `archives` for `archive`. Phrases had no such luck, so the shipped
   programmes were unequally exposed.
2. Severity rose to `high` only when *another* programme cleared a two-hit floor, and
   two of the four shipped Archives keywords — `snapshot` and `historical` — are
   ordinary data-delivery vocabulary that appears in a specification for any programme
   at all. Archives cleared the floor by accident, so a delivery whose own words were
   missed was not merely raised for review: it was confidently reported as a different
   programme, at the highest severity the tool has.

**Decision:** Match loosely, count strictly.

**Loosely**, in `checks/programme_match.py`: three tests, any of which finds a keyword —
a normalised substring (which preserves every match the old behaviour made, inflections
included), the keyword's words adjacent after a conservative singular fold, and, for a
multi-word keyword only, its words within a stated window of each other in any order.
The fold is deliberately not a stemmer: it removes a plural and nothing else, because a
false match here has to be explainable to the person reading the finding.

**Strictly**, in the severity decision: a programme may be named as what a delivery
"reads like" only on words **it alone claims**, and only when it is strictly ahead of
the next programme. A word two programmes both list cannot tell them apart whoever
added it, and a tie means the inputs are unfamiliar rather than evidence for either.
The shipped lists also lost the two words that meant nothing and gained the words the
business actually says.

**Consequences:** The same twenty deliveries now measure 15 silent, 4 review and **1
high**, with the control class — deliveries genuinely declared as the wrong programme —
unchanged at 3 of 3. The check stays a grep: free, reproducible, and explainable to an
auditor, which is the property worth protecting.

The remaining high is kept deliberately and is the reason
[`phase-6.18.md`](phase-6.18.md) 6.18f exists. A prescreen delivery that calls itself a
*promotional acquisition mailing* and suppresses `existing accounts` has two of Account
Monitoring's words and none of its own. **Nothing is misspelled** — the words really are
the other programme's, and what makes them innocent is that they appear under *suppress*
and *removes*. That is meaning, and no spelling rule reaches it. Closing it is the
model's job, asked once after the code check has failed and answering *which programme
does this read like*, never *is this correct*, which stays code's (ADR-001).

The structural guard matters more than the keyword fix it replaced: removing `snapshot`
and `historical` corrected one instance, and "a programme is named only on words it
alone claims" is what stops an administrator recreating it with the next overlapping
word they add.

## ADR-043 — A finding earns its way out of the review queue on human verdicts alone, and earns it in shadow first

**Status:** accepted 2026-09-20 (Phase 6.18a, user decision).

**Context:** The product's value at volume is a reviewer who reads the findings that
matter instead of all of them. The tool has recorded every verdict a reviewer gave since
Phase 6.11 and displayed a per-rule fired/dismissed tally since 6.13, and **nothing has
ever read either**. Meanwhile a misreading had taken hold, in conversation and in review:
that ADR-021 requires a person to see every finding. It does not. It requires a person
at the gate of a **rule**, and approving a rule is precisely the act of saying *apply
this without asking me again*. A tool that keeps asking has wasted the approval.

**Decision:** Group findings into **signatures** and let a signature stop reaching the
review queue when the people who saw it have consistently said it did not matter.

- **A signature is one customer, one delivery programme, one rule, and one thing it
  fired on.** Trust is shared across a customer's deliveries within a programme and
  never across programmes, because a control genuinely is implemented differently under
  Account Solicitation than under Archives. The thing it fired on is part of the
  identity: a blank score column and a blank state column share a rule and are not the
  same finding, and pooling them would let evidence about a harmless case silence one
  that matters.
- **Ten occurrences, every one waved through.** A count with no exceptions in it, not a
  rate. *"It was shown to a person ten times and never once mattered"* can be said to an
  auditor; *"nine times out of ten"* cannot, because the tenth is the one that would
  have been hidden. The count is settable upward; what a verdict means is not.
- **One upheld finding blocks the signature permanently**, until a person clears it.
  `accepted_risk` counts as upheld, not as a dismissal: the reviewer agreed the finding
  was true and chose to carry it, which is the opposite of saying it should never have
  been raised.
- **`high` and above are never demoted**, at any level of evidence. The goal is a
  reviewer who reads only the serious findings, not one who reads none.
- **Nothing returns on its own.** A demotion is undone by a person or by a new verdict
  upholding the finding, never by elapsed time — ADR-021's rule that nothing in the
  training record expires by itself.
- **Findings from a rule in shadow are not evidence.** A rule nobody has been shown
  cannot have earned anybody's trust, and counting them would let a shadow rule demote
  itself.
- **The decision is arithmetic over human verdicts** (ADR-001). The model is not asked
  whether a finding is important, and a model's stated confidence is not evidence here.
  Confidence is used elsewhere in this product to *discard* a weak answer and never to
  *trust* a strong one; that asymmetry stays.

**And it ships in shadow.** 6.18a computes every signature's state, records it with the
runs whose verdicts justify it, and **changes nothing about what any reviewer sees**.
That is deliberate: the first evidence about whether demotion is safe must not be a
reviewer failing to see something. After some weeks there is a real list to put the
question to — *it would have hidden these forty; was any of them real?* — and that
evidence is what 6.18b acts on and 6.18c measures.

**Consequences:** One table, `finding_signatures`, which is a cache of an answer
derivable from `findings` and `runs`; it exists because a demotion must be explainable
months later, so it stores the sentence and the run ids rather than only the verdict.
Recomputation reads every finding sharing a signature rather than adjusting a counter,
so a corrected verdict or a deleted run lands correctly with nobody remembering to undo
anything. `GET /admin/demotion-report` is the shadow report.

What this does **not** do is remove a human from signing off a delivery. The finalize
attestation of Phase 6.11 is untouched. What shrinks is how many findings a reviewer
must read before they can honestly sign — not whether they sign.

## ADR-044 — The compliance locator is told the run's programme and its standing instructions

**Status:** accepted 2026-09-20 (Phase 6.17c, user decision).

**Context:** When the deterministic compliance matcher finds nothing, stage 6 asks the
model where the control is, if anywhere. `phase-6.15.md` left open whether that prompt
should be told which programme the run belongs to. The question was written as though
it were not, and **the shipped code already was**: `_locate()` prepends
`preamble(context.guidance)`, which emits the programme's label and that programme's
standing instructions. Nobody decided this; it arrived with the preamble.

Nothing asserted it either, so a refactor could have dropped it, or doubled it, with
every test still passing.

**Decision:** Keep both, pin them with tests, and record the decision that was never
made.

The argument for is the one 6.15 anticipated: OFAC screening may be implemented
differently under Account Solicitation than under Archives, and the model cannot know
that from a configuration alone. The argument against is real and specific to this
prompt — it is the only call in the product whose answer can soften a high-severity
compliance finding — but it is bounded by guards code already applies: the model may
only quote a path from the list it was given, must clear a confidence floor, must
answer `found` rather than hedge, and **a located control is never a pass**. It becomes
a review-severity question for a person. A standing instruction cannot clear a
requirement; at worst it costs a reviewer one more question.

**Consequences:** Four tests in `tests/pipeline/test_compliance_locate.py` now assert
what reaches this prompt: that the programme and its standing instructions arrive, that
they are labelled as background rather than as a requirement, that the preamble is sent
once rather than twice, and that a run with nothing configured sends no preamble at all,
so the prompt is byte-for-byte what it was before any of this existed.

The narrower option — sending the programme label but not the administrator's free text
— stays available and is a one-line change if a measurement ever shows the prose
steering an answer. Running that measurement needs a real model, since the mock always
answers `absent`; it is worth doing if the locator is ever seen to be too generous, and
is not worth blocking on now.

## ADR-045 — The model reads a delivery for its programme only where the keywords failed, and may soften a finding but never erase one

**Status:** accepted 2026-09-20 (Phase 6.18f, user decision).

**Context:** Phase 6.17a measured the programme classification check, found it brittle,
and repaired it deterministically: false high-severity findings fell from five to one.
The one left is not a spelling problem. A delivery that calls itself a *promotional
acquisition mailing* and says *suppress existing accounts* carries two of Account
Monitoring's words and none of Account Solicitation's. **Nothing is misspelled** — the
words really are the other programme's, and what makes them innocent is that they
appear under *suppress* and *removes*. That is meaning, and no normalising rule reaches
it.

The user asked for both paths — *"consult the AI after checking programmatically"* —
which is the shape `phase-6.15.md` option A already established for compliance rules.

**Decision:** Code first, the model once, code decides.

1. **The keyword match runs first.** A hit anywhere and the check is silent, free and
   explainable. The common case costs nothing, which is what makes asking affordable at
   all: this is one call per delivery, and only on deliveries the keywords missed.
2. **The model is asked one narrow question** — *which of these programmes do these
   documents read like, and which words say so?* It is **never** asked whether the
   submitter was right; that is a comparison, and comparisons are code's (ADR-001). The
   prompt tells it that the deterministic match has already failed, and that "unclear"
   is a good answer, because unfamiliar vocabulary is more common than a mis-declared
   delivery.
3. **Code refuses what it cannot believe**: a programme code nobody offered, an answer
   below a confidence floor, an unparseable reply, or no reply. Each falls back to the
   deterministic answer, which is what the check would have had anyway — so asking is
   never worse than not asking.
4. **Code decides what a believable answer means**, and this is the rule that keeps it
   safe:
   - The model **disagrees** with the declaration → the high-severity finding the check
     exists for, now with a reason a person can read.
   - The model **agrees**, and code had only *"none of its words appear"* → silent. That
     finding was a word-list gap, which is an administrator's problem and not a
     reviewer's, and raising it on every delivery from that customer forever is the
     noise Phase 6.18 exists to remove.
   - The model **agrees**, and code had enough to name a different programme → the
     finding **drops to review severity**. It is not erased. A model agreeing with the
     submitter is the one answer that could hide a real mismatch, so it buys a question
     rather than a silence — the same line the compliance locator holds.
   - The model is **unclear** → review severity, and it never raises one.

**And the loop closes in code, not in the model.** When the model agrees, the phrases it
quoted are recorded on the run and offered to an administrator on the programme's card.
Accepting one adds it to the keyword list; from then on the check matches that
customer's vocabulary deterministically and **the model is not asked again**. The tool
stops asking because code now knows, not because the model grew confident — which is the
distinction this product keeps everywhere (ADR-043). Nothing is applied without a person
(ADR-021).

**Consequences:** One new prompt, `programme_reading`, versioned and cached like every
other. `Run.keyword_suggestions` holds what was quoted. `docs/model-context.md` records
that a delivery's own words now reach a model at stage 7, capped, and never a data row
(ADR-003) — the prompt is told not to quote a phrase containing a person's details, and
the tripwire scans it like every other.

The cost is one model call per delivery whose keywords missed, falling to zero for a
customer as their vocabulary is accepted. The benefit is that the last measured false
high-severity finding in the classification check has an answer, and that a customer
who writes about their work in their own words stops being asked about it every month.

## ADR-046 — A marker may be switched off only where it says a field is *not* read in a run

**Status:** accepted · 2026-09-20 · Phase 6.19

**Context.** Every field a person can write carries a `<FieldEffect>` marker saying what
it does to a run, and until now the rule was absolute: **markers never hide.** The
reason is in `CLAUDE.md` — an administrator cannot see a prompt, so the label beside the
box is the only account they get of where their words end up, and a console that stops
giving that account once somebody ticks a box is a console that lies to its experienced
users. `ui.tooltips` turns off *help*; it has never touched the markers.

Phase 6.19 then added a sixth kind, `reference`, for material the AI reads **while
somebody sets the product up and never during a validation run**: the sample workbooks,
and an artifact type's description. On the Artifact types screen that marker repeats
under every sample in every scope group, saying the same sentence each time.

**Decision.** `reference` — *"Used for setup, not for runs"* — is switchable, with
`ui.setup_markers`, on by default. The other four are not, and the asymmetry has a
reason rather than being a convenience:

- A marker that says a field **reaches the model** or **is checked by code** is
  accountability. Hiding it leaves somebody writing a careful paragraph with no idea it
  will be read, or no idea it will not. That is the defect the markers exist to prevent.
- A marker that says a field is **not read during a run** cannot mislead anybody about
  where their words go. Switching it off removes a repeated reassurance, not a fact
  somebody needed.

The distinction is the direction of the claim, not how useful the sentence is.

**Consequences.** `FieldEffect` consults one setting, in one line, for one kind:
`if (kind === "reference" && !setupMarkers) return null;`. It does not consult
`ui.tooltips` at all. Two tests hold the line —
`test_the_marker_cannot_be_switched_off` keeps help and markers apart, and
`test_only_the_setup_marker_may_be_switched_off` asserts the *shape* of that guard, so
widening the condition fails even though every rendering test would still pass. The way
this decision would erode is somebody adding `|| kind === "notes"` to a line nobody is
watching.

The switch lives in Appearance beside **Explain each screen**, because the two are what
an administrator reaches for when a console feels chatty — and the help text says
plainly which markers it cannot touch, so nobody switches it expecting more silence than
they get.

## ADR-047 — A failed run stores a traceback, and it is shown on the run rather than in the list

**Status:** accepted · 2026-09-20 · Phase 6.19

**Context.** A failed run carried one string. The runs list truncated it to forty
characters and the run page showed the whole of it, which sounds like two views of one
failure and is really one view twice: *"PipelineError: s4_trace: 3 requirements did not
resolve"* says what happened and nothing about where it came from. Anybody reporting the
failure had to be told to go and read a worker log they cannot reach.

**Decision.** Two fields, answering different questions. `Run.error` stays one line —
*what* — and is what the list shows. `Run.error_detail` is *where*: the stage, the
attempt, and the traceback through this codebase, written by
`worker/diagnostics.py::describe_failure` on both failure paths. It appears on the run
behind a closed disclosure with a copy button, and **never in the list payload**, which
a test asserts.

**Why a traceback is allowed at all.** ADR-003 keeps delivery content out of logs and
prompts, and a traceback is where that could be broken by accident, because a frame's
message can quote whatever was being parsed. It is safe here because of how the pipeline
raises: `PipelineError` carries a stage and a reason written in counts and ids, never a
value from a workbook, and nothing formats local variables. What is stored is frames, an
exception type, and that reason.

**Consequences.** It is bounded at both ends: the whole text is capped at 8,000
characters, dropping the **oldest** frames because the innermost call and the exception
are at the end, and saying so rather than showing a trimmed traceback that looks
complete. The header's copy of the exception message is capped separately at 500 — a
parser that quotes what it choked on can raise something enormous, and the header would
otherwise consume the whole budget and leave a detail with no frames in it. Both caps
are tested against a deliberately vast message.

The detail is written for a run awaiting a retry too, not only a dead one: the attempt
that failed is what somebody wants to see, and the next attempt overwrites it.

## ADR-048 — Usage is counted per person, and the three ways a run goes wrong are counted apart

**Status:** accepted · 2026-09-20 · Phase 6.19

**Context.** The usage dashboard counted the deployment, which answers *is anybody using
this* and nothing else. The question an administrator arrives with is narrower: **is this
going badly for a particular group of people?** A team whose runs fail twice as often as
everyone else's is either meeting a report layout the parsers do not handle or has been
taught the product wrong. Both are fixable and neither is visible in one average.

**Decision.** `user_usage.build` counts per account over a closed set of periods — 7, 30,
90 and 180 days, defaulting to 30 — and **keeps the three failure modes apart**, because
they have different causes and different fixes:

- **Failed** — the pipeline raised. Usually the tool's problem.
- **Held** — the artifacts disagreed with the form (ADR-041). Usually a person's, and
  the most teachable of the three.
- **Re-run** — the same order submitted again. Something was wrong either way.

A single "problems" count would hide the only thing worth knowing, which is which of the
three an administrator can act on.

**Rates are reported against the deployment's own average**, not a threshold. *Twice
everyone else* is a fact somebody can act on; *a score of 68* is not, and nobody can
argue with it. A row under five runs is never flagged, because a rate over three runs is
noise whatever it says.

**Consequences.** The period list is closed rather than a range, so the report cannot be
asked for ten years of days by editing a URL; an unknown period is a 422 naming the four.
The per-day series is **sparse** — a day with no runs is absent rather than zero —
because a 180-day period is mostly zeroes. Days are UTC days, the frame run timestamps
are stored in; taking "today" from a local clock counts the wrong day for anybody west of
Greenwich in the evening, which is a bug this phase found in the value report's tests.

A count links to that person's runs, which needed `GET /runs?submitted_by=` — an account
id rather than a name, because two people can share a display name and a link that
quietly widened to both would be worse than one that found nobody. The user app gained
the matching filter and a search that covers the submitter, so somebody can answer the
same question about themselves.

**This is a count, not a judgment.** Deactivated accounts still appear: what somebody did
does not stop having happened (ADR-022). Nothing here reaches a model, and the console
says so on the card.

## ADR-049 — Roles grant capabilities, a person holds several, and code asks about capabilities

**Status:** accepted · 2026-09-21 · Phase 6.20

**Context.** There were two roles — `admin` and `user` — and no matrix. `role ==
"admin"` was written out in five routers, and the model's own comment said *"two roles,
no permission matrix"*. That is workable for two and stops being workable at three.

Two things were wrong in the product. The user app showed **everybody** the admin console
link, so somebody who could change nothing there was still invited in. And there was no
role for the person the whole training loop was built for: a senior associate who knows a
programme well enough to approve what the tool learned from it, but who should not be
creating accounts or editing what the tool may send to a model.

**Decision.** Three roles — `user`, `reviewer`, `admin` — and **roles grant
capabilities**. No router asks whether somebody is a reviewer; it asks whether they may
approve training, and `auth/roles.py` answers. Adding a fourth role is an edit to one
table rather than a search through five routers, and *what can a reviewer actually do?*
has an answer that is read rather than reconstructed.

**A person holds several roles**, and capabilities are the union, so holding more roles
never takes anything away. A senior associate is a `user` and a `reviewer`; an
administrator is nearly always a `user` too.

**The line between reviewer and admin is judging the work versus defining the
deployment.** A reviewer decides whether a rule is right. An administrator decides what a
programme is, who has an account, and what the tool may send to a model. Different jobs,
different blast radius, and the second group is much smaller.

Three judgement calls are recorded so they can be argued with rather than discovered:

- **Masked columns are admin-only although the rest of Reference data is not.** Naming a
  column there is what keeps personal data out of every prompt (ADR-003) — the strongest
  control in the product and the one whose failure is least visible, because nothing goes
  wrong on screen when a column stops being masked. Aliases and field labels carry none
  of that risk and stay with the reviewer.
- **Reviewers get the rule surfaces, not only the training queue.** Approving an
  observation produces a rule, and a rule the approver cannot then activate makes the
  role a half-job that always needs an administrator. Shadow-then-activate (ADR-021) is
  what makes it safe: nothing activated starts producing findings without having run
  silently first.
- **The delivery programme *list* stays on the console floor, although writing one does
  not.** Four screens a reviewer works on — checks, compliance rules, worked examples and
  reference data — scope what they are editing to a programme, so all four fetch the
  list. Reading it is not *managing programmes*, and refusing it would take four of a
  reviewer's own screens away to protect a listing the console links to anyway. Creating,
  editing or deleting a programme, and its keywords and rules, need
  `MANAGE_PROGRAMMES`.

**Consequences.** This has **no effect until login is switched on**. ADR-022 ships it
off, and with it off `deps.py` hands the placeholder `is_admin=True` — which must stay
true, because ADR-022 promises that with both switches off the behaviour is exactly what
it was before login existed. So the enforcement is built before the hiding, a hidden link
is never mistaken for a closed door, and the acceptance criteria are tested with login
**on**, which no existing UI test does.

**How a route asks.** `require_capability(Capability.X)` builds one guard per
capability, and a route names the act it performs rather than the role that may perform
it. Two routes serve several resources — a bulk delete over five tables, a revert of any
definition — so they take the console floor as a dependency and call `assert_capability`
once the parameter says which capability actually applies. The refusal is **403, never
404**, and it names what was missing: the screen exists and is not theirs, there is
nothing secret in the name of an endpoint the console links to, and a bare refusal makes
a support conversation impossible.

**Neither console knows the matrix.** `GET /auth/me` returns the resolved capabilities and
both apps read them. A console that recomputed the matrix would disagree with the API the
first time a grant moved, and would disagree in the worst direction — by offering a screen
that then refuses.

**The role list is the only stored answer.** A single `role` column stood beside it while
the callers were moved over and was dropped in `d2f4a6b8c0e1`. Two answers to one question
is where the two get to disagree, and an account behaving as an administrator while its
row says otherwise is how somebody gets locked out. Membership is tested in Python, not
SQL: JSON containment is spelled differently on SQLite and Postgres (ADR-017) and the
users table is the smallest in the schema.

**The last administrator cannot be removed**, by unticking `admin` or by deactivating the
account, including by the caller doing it to themselves. Locking everybody out of the
console cannot be undone without editing the database, so it is refused rather than
warned about.

Refused, for now: **per-object permissions**. "Reviewer for programme AM only" would
overload `scope`, which already means something specific (ADR-029), and make both harder
to reason about. And **no permission editing in the console** — a console that lets
somebody grant themselves `MANAGE_SETTINGS` has one role in it.

## ADR-050 — The in-product Guide is generated from the training document, and can be switched off

**Status:** accepted · 2026-09-21 · Phase 6.19b

**Context.** The rollout plan asks the senior associates for an hour of training per
region. An hour teaches where the buttons are. It cannot teach the things that decide
whether the tool is worth having — which fields are worth writing carefully, what the tool
is not looking at, when to disagree with it — and those are written down, in
`docs/user-training.md` and `docs/admin-training.md`, where nobody using the product will
ever see them.

The obvious fix is a Guide screen in each app. The obvious failure of that fix is a second
document: a Guide written once, drifting from the training document within two phases,
and nobody able to say which of the two is right.

**Decision.** Each app carries a **Guide** in its sidebar, and its content is
**generated** from that audience's training document by `scripts/build_guides.py`. The
documents declare what belongs in the Guide, where, and under what title:

    <!-- guide 4: How to read a finding, and how to decide -->
    ## Reviewing findings

The title is stated separately because a document heading is written for somebody reading
front to back and a Guide heading for somebody who arrived with a question. Selection and
order are in the document, so the Guide stays "a screen written for the person in front of
it" rather than the document in a frame — and there is still only one source.

**It is enforced, not remembered.** `scripts/check_docs.sh` and
`tests/docs/test_guides.py` both compare the generated file with what the document
produces now, so a session that edits a training document and does not rebuild fails the
gate it already runs.

**The generator emits parsed blocks, not markdown.** Headings, paragraphs, lists and
tables, with inline emphasis resolved into spans. Neither app carries a markdown renderer,
and a regex one written in the browser would be a new class of bug in a screen whose whole
job is to be trustworthy. Parsing once, in a checked script, is cheaper and safer — and
the tests assert no markdown survives, because anything the parser leaves reaches a
person's screen as punctuation. Mermaid diagrams are dropped: they are the document
explaining a flow to somebody studying it.

**It can be switched off**, by `GREENLIGHT_AI_UI_GUIDE` or from the admin console, on by
default (ADR-023). Some deployments deliver training another way and would rather not keep
a second copy current. The switch gates the link and the screen and nothing else: help is
not a control, so turning it off cannot change what a run does, and the API does not
consult it.

**Consequences.** Editing a training document is now a two-step change — edit, rebuild,
commit both — and the gate says so when it is forgotten. The Guide can only contain what
the training document contains, which is the point: a section worth showing in the product
is a section worth having in the training document, and writing it there first means the
people who train from the document get it too.

---

## ADR-051 — The report chat is run-scoped, read-only, and keeps nothing

**Status:** accepted · 2026-09-21 · Phase 8

**Context.** A person reading a frozen report has questions the page does not answer: why
this finding is high, whether it appeared last month, what the rule actually says, what
nobody checked. All of it is in the database. None of it is on the page. A chat box on the
report is the obvious answer, and the obvious implementation is the wrong one in three
separate ways.

The first is context. Asking a model to read "the run" invites sending it the uploaded
workbooks, which ADR-003 forbids and the tripwire refuses. The second is arithmetic: a
chat box is exactly where somebody asks a model to add two numbers, and ADR-001 says code
does every comparison. The third is isolation — a conversation store keyed on anything
looser than the run is a place one person's delivery reaches another's screen.

**Decision.** The chat sees a **context pack** that code assembles from the database, for
one run, on the server, on every turn. It is never accepted from the client, because a
client that can supply context is a client that can supply facts.

The pack holds the global rules in force, the previous finalized run of the same
configuration id, the findings of the last three finalized runs with the decisions people
made on them, this run's findings and their evidence, an **inventory** of the artifacts —
kind, label, checksum and counts, never contents — the run's own guidance, the coverage,
the notices, the attestation, the drift, and the frozen report's rendered text. Every one
of those already appears in the *Allowed in a prompt* column of
[`llm-privacy.md`](llm-privacy.md). Shadow findings are excluded, exactly as the frozen
report excludes them: a rule nobody activated must not start answering questions either.

**It is available only on a frozen run.** A conversation whose context shifts as decisions
are made gives answers that were true when given and are not now. Freezing is what makes
an answer reproducible.

**Nothing is stored.** The transcript is state in the browser and dies with the panel.
There is therefore no conversation table to retain, secure, or leak from, and the question
of whose transcript an administrator may read does not arise. The cost is real and is
accepted: a question asked last week cannot be recovered. The model call itself is
recorded like every other — ids and counts, never text — so the usage is visible without
the content being kept.

**A person may copy their own conversation to the clipboard**, which is the one
concession and is deliberately not a feature of the tool's storage. Somebody who wants to
keep an answer pastes it into their own notes or a ticket, and the responsibility for
where masked-but-real delivery detail ends up moves to the person who chose to move it.
That is the right place for it, and it is honest about what would otherwise happen anyway
by selecting text.

**It acts on nothing.** No decision, no finding, no rule, no re-run, no regenerated
report. Everything it can do is read.

**Isolation is five independent things, not one.** The pack is server-built from the run
id; the endpoint refuses anyone who may not read that run; nothing is stored; the cache is
content-addressed with the pack hash in the key, so a hit requires the same question
against the same run's pack; and the browser holds the transcript in component state
rather than in `localStorage`.

**Consequences.** The chat cannot answer a question about a cell value, and says so rather
than guessing — which is the behaviour the acceptance criteria test hardest. A context
builder now exists outside `pipeline/`, which is why the shared text-fitting helpers move
into a neutral module: `api/` may not import `pipeline/`, and a chat package that did
would break that rule transitively and invisibly.

## ADR-052 — Report aggregates reach the chat only behind an administrator's switch

**Status:** accepted · 2026-09-21 · Phase 8 · extends ADR-003

**Context.** ADR-051's pack answers most questions about a report and cannot answer one
shape of question at all: what a field's distribution looks like, where the nulls are, how
many distinct values a column holds. Those are aggregates, and
[`llm-privacy.md`](llm-privacy.md) has always allowed aggregates in a prompt — minimum,
maximum, mean, count, null count, distinct keys. What it has never done is compute them
for every column and hand them over by default.

Two bad answers were available. Loosen the rule for everyone, and a deployment that never
wanted this gains it on upgrade. Refuse outright, and the tool cannot answer a question it
is allowed to answer.

**Decision.** The pack ships **strictly derived**. An administrator may switch on a
widened pack that adds **per-column aggregates computed by code at parse time**. Never a
row. Never a cell that is not an aggregate. The tripwire runs on the assembled prompt
regardless and still fails closed.

The setting resolves through the three configuration layers of ADR-023, so it can be
changed without a deploy, and it is **never** settable anywhere but the console and the
environment.

**It is labelled as strongly as masked columns are.** An administrator cannot see a
prompt, so a marker is the only account they get of what a setting does. This one changes
what leaves the building, and the console says exactly that rather than describing it as a
richer answer.

**Consequences.** There are two shapes of pack, so the acceptance test for "no
non-aggregate value" runs against both. The aggregates must be computed where masking
already happens, at parse time, rather than read back out of a report later — a value
computed after masking is a value that was never masked.

## ADR-053 — The chat streams its prose, and shows a citation only after code has checked it

**Status:** accepted · 2026-09-21 · Phase 8

**Context.** The adapter has one entry point, `complete(system, user, schema)`, and every
invariant the tool depends on sits behind it: the PII tripwire, the cache check before
every call, the budget stop, the single schema-validated retry, and the per-call record
(ADR-004, ADR-005). It is single-turn and it does not stream. A chat box wants both, and
an answer that appears whole after a silent wait is the difference between a feature
people use and one they try once.

One objection to streaming can be dismissed immediately, because getting it wrong would
distort the whole design: **streaming does not weaken the tripwire.** The prompt is
assembled and scanned in full before a single byte is sent; only the response streams
back. Nothing about personal data leaving the building changes.

The real conflict is narrower and cannot be dismissed. The answer is schema-constrained,
and code checks that every citation resolves to an id that is actually in the pack before
showing it — a fabricated finding reference is the failure that would most damage trust in
a QC tool. **Code cannot check what has already been displayed.** The single retry has the
same shape of problem: once prose is on screen, re-asking silently is not available.

**Decision.** The chat streams, and the structure it is judged on does not.

**The prose streams; the citations do not.** The model writes the answer as plain prose
containing **no finding ids**, then emits a structured tail naming what it answered from.
The prose reaches the panel token by token. The tail is validated against the pack when
the stream closes, and only the citations that resolve are rendered. A fabricated id is
therefore never shown as a citation — not briefly, not dimmed, not at all.

**Streaming lives in the adapter.** `llm/` gains a streaming entry point beside
`complete`, rather than a second network path in `api/` or `chat/`. The tripwire, the
cache check, the budget stop and the per-call record continue to happen in exactly one
place. This amends ADR-004's "one entry point" to "one module", which was always the rule
that mattered: what must not spread is the network call, not the method count.

**A malformed tail keeps the answer.** The panel says the citations could not be verified
rather than showing chips, and nothing is re-asked. Pulling text somebody is part-way
through reading looks like a malfunction even when it is correct behaviour, and the prose
answers the question on its own. This is the one place the single-retry contract does not
apply, and it is written here so that it is a decision rather than a later surprise.

**A cache hit is served whole.** The cache is checked before the stream opens, as before
every call. A hit replays the stored answer and its stored citations with no network call;
a miss streams, and the answer is stored only when the stream closes. **A partial answer is
never cached**, so an interrupted conversation cannot poison the next one.

**Multi-turn is flattening.** Earlier turns are rendered into the user prompt inside a
delimited block, labelled as a person's words to interpret and never as instructions to
follow — the technique ADR-021 already uses for reviewer statements, for the same reason.
The cache key therefore covers the whole transcript, so a hit is only ever an exact repeat
of the same conversation against the same pack.

**The chat resolves its own model**, through the three layers of ADR-023, defaulting to
the pipeline's when unset. Conversation and schema-constrained extraction are different
jobs and may deserve different models or different costs; because the model name is
already part of every cache key, the two can never serve each other's answers.

**Consequences.** There is now a streaming path to test as carefully as the answer itself:
an interrupted stream must store nothing, and a fabricated citation must not reach the
panel. Both are acceptance criteria rather than hopes. A long conversation re-sends its own
history, so the transcript is capped in turns and the cap is a setting rather than a
constant. And the prompt must hold the model to prose without ids, which is a real
instruction-following burden — the citation check is what makes a lapse harmless rather
than embarrassing.

---

## ADR-054 — One ladder resolves every name, code first and the model last

**Status:** accepted · 2026-09-21 · Phase 6.21a

**Context.** Every comparison this product makes eventually reaches a *name* somebody
else chose: a worksheet, a column heading, a row label, a configuration key. Four
modules reduced a name to a comparable form with four slightly different rules, and
every one of them stopped at exact-after-lowercasing. `checks/reports.py` named its
sheets as Python constants and matched them exactly, so a delivery whose attribute
sheet is called `Attribute Summary` matched nothing and every check that needed it
became a `could_not_evaluate` finding. The run was honest — the finalize gate refuses
to freeze a report over an unacknowledged gap (ADR-035) — and it validated nothing.

Phase 6.15 had already solved the same problem for compliance rules, and 6.17a for
programme classification. The shape was proven; it was simply not pointed at the
surface where drift lands.

**Decision.** `src/greenlight_ai/resolve/` is the only place that answers *which name
was meant*, as a ladder tried in order: **exact** (case and surrounding space aside),
**squashed** (separators are noise), **tokens** (the same words, singular or plural, in
order, with at most two more besides), **alternate** (a synonym a person wrote down),
then **the model**, shown names and nothing else.

Two rules make the result defensible:

- **A rung that ties is a rung that failed.** Two candidates matching equally well is
  the case a person or the model should settle; picking one would be a comparison
  nobody could reproduce. The ladder falls through with every candidate still on the
  table.
- **A later rung never overrules an earlier one.** The rungs are ordered by how much
  they assume, so nothing that matched before this package existed stops matching.

The fifth rung obeys the discipline 6.15 established and this ADR restates: the model's
answer must be one of the names it was offered, a confidence floor of 0.6 applies, and
**it is never a pass**. What it resolves produces a `layout_reasoned` review finding
naming what was wanted, what was used and how sure it was, so a reviewer can disagree
with the *reading* rather than only with the finding. A run with no client, or one
whose budget is spent, gets the deterministic answer.

**Consequences.** Report layout stops being a reason a run reports nothing. The cost is
one model call per distinct unresolved name per run, cached like any other, and it
falls to zero once an administrator accepts the answer onto the artifact type
(Phase 6.21b). Four normalisers became one, and a fifth would be the defect this
decision exists to prevent.

Two things this changed that were not the point. A counts report can carry a waterfall
step called `input` *and* a total called `Input`; they are different rows and the old
lookup picked whichever the workbook listed first, so rung 1 now settles it by spelling
and falls back to first-wins only when spelling does not decide. And `recheck()`'s
guard that a re-check makes no model calls counted **rows** in the call log, which
includes cache hits — so it would have fired on a re-check that behaved perfectly. It
counts tokens now, which is what "the re-check is free" has always meant.

---

## ADR-055 — The answer's schema is sent with the request, and the endpoint may refuse it

**Status:** accepted · 2026-09-21 · Phase 6.21e

**Context.** `docs/design.md` has said since Phase 2 that *"if the serving stack
supports guided or JSON-schema decoding (vLLM does), turn it on — it removes most
format errors"*, and nothing sent it: both clients posted only the model, the messages,
`max_tokens` and `temperature`. Recovery from a malformed answer was one retry with the
validation error appended. Phase 7 runs on a 20–40B in-house model, which is exactly
where format errors are common and where this is the largest reliability gain available
for the smallest change.

**Decision.** `llm.guided_json` takes `off`, `auto` or `on`, defaulting to **`auto`**.
Where there is a schema and the mode allows it, the OpenAI-compatible client sends
`response_format: {type: json_schema, …}` and the Anthropic client requires a single
tool whose `input_schema` is the same shape — the Messages API has no `response_format`,
and a forced tool is how an answer is constrained there.

**A refusal is handled without reading the body.** Which field an endpoint disliked is
not knowable without parsing an error that may echo the prompt (ADR-003), so the rule is
the simple one: under `auto`, **any** 400 on a guided request means drop the field,
retry once, and stop offering it for the rest of the process. A gateway that has never
heard of it therefore costs one wasted call per process rather than one per stage, and
is not a broken deployment. Under `on`, an administrator has said they want it: nothing
is latched and the refusal surfaces as the error it is.

Every call record carries `guided`, so what the setting bought on a given serving stack
can be measured rather than assumed.

**Consequences.** `_send` gained the schema and now returns a `Sent` value object rather
than a tuple, which is the only change any provider had to make. A 500 is still an
ordinary failure: only a 400 reads as a refusal of the field, because only a 400 means
the request itself was rejected.

---

## ADR-056 — The tool may report what no rule covers, at the bottom of the severity scale

**Status:** accepted · 2026-09-21 · Phase 6.21c

**Context.** Every finding this product made traced back to a rule somebody authored: an
OSL requirement, a compliance control, an administrator's check. That is the right
default — a finding nobody can explain is a finding nobody acts on — but it means the
tool could only ever find what it had been told to look for. `docs/design.md` has
promised a `profile_anomaly` finding since Phase 2 ("unexpected nulls, wrong type, mean
far from prior runs"). The type was declared in `rules/schema.py`, labelled in the user
interface, used as an example in the stage-9 prompt, and **constructed nowhere**.

**Decision.** Each finalized run stores the shape of what it delivered — per attribute,
a null rate, a minimum, a maximum and a mean — and a later run of the same configuration
is compared against them. Two halves:

- **Code, by default.** The median and median absolute deviation of the previous
  finalized deliveries, not the mean and standard deviation: with a handful of runs a
  single odd delivery drags a mean far enough to hide the next one, and the median does
  not move. A perfectly flat history has no spread to be a multiple of, so a relative
  threshold applies there instead.
- **The model, off by default.** One call, shown the same aggregates, asked what looks
  unusual on its own terms. It is the only call the product makes on *every* run, which
  is why it ships off.

**Three constraints make this safe to ship.**

1. **It says nothing until it has enough history** (three deliveries by default). A
   baseline of one delivery is not a baseline, and a tool that invented one would teach
   reviewers to ignore the whole category in its first week.
2. **Code grades it, and grades it low.** Code cannot know whether a mean moving three
   percent matters for this attribute in this business, and severity is code's to set
   (ADR-001) — so it sets the one that means *look when you have a moment* and puts the
   numbers in the finding for a person to judge. The model half is **review**, because
   it has a reading behind it rather than arithmetic.
3. **It is measured.** `scripts/anomaly_benchmark.py` and
   `docs/benchmarks/phase-6.21-anomaly.md`: 92.3% precision, 100% recall on synthetic
   histories. An anomaly detector nobody measured is a false-positive generator, and the
   failure that matters is not a wrong finding but a reviewer learning the category is
   noise.

**Aggregates only** (ADR-003). A null *rate*, not which rows were null; a minimum, not
the record that held it. That is what makes the profile safe to store for the retention
window and safe to show the model.

**Consequences.** A configuration's first few deliveries get no anomaly findings, which
is correct and will read as the feature being broken until somebody reads this. The
stored profile is one more thing the retention purge removes with a run. And the
thresholds are console settings rather than constants, because the number that survives
contact with real deliveries is a Phase 7 question — the benchmark bounds the
arithmetic, not the product.

Building the benchmark corrected an assumption worth recording: a null rate up 40% on a
measure that has sat at 4.0% ± 0.2% for eight deliveries **is** eight deviations out,
and firing on it is right. What counts as a nudge is relative to how much that measure
normally moves, which is the whole reason this compares against a spread rather than a
fixed percentage.

## ADR-059 — An attribute name code cannot resolve is "could not evaluate", not a violation

**Status:** accepted · 2026-09-21 · Phase 6.22a

**Context.** `checks/reports.py` answered "does the DIRT carry this attribute?" in two
places and gave two different answers when it did not know. `_check_fields_present`
tested `resolve(name) not in stats` and, on a miss, returned `passed=False` — which
stage 7 publishes as `report_violates_rule` at **high** severity. `_check_bound`, for
the very same miss, returned `passed=None` and became `could_not_evaluate` at `review`.
A third copy of the test sat in `checks/field_constraints.py`.

The louder of the two was wrong. An OSL that asks for `AT01` against a DIRT column
named `debsc_burs_atyrt_at01_1` describes a delivery that is entirely correct, and the
tool asserted as fact, at the top of the severity scale, that it was missing an
attribute it had in fact delivered. Because `stats` was non-empty the check never
degraded, so the finalize gate (ADR-035, ADR-036) then required a person to acknowledge
something untrue. Measured on the `attribute_renamed` fixture: **one high-severity
finding naming all ten delivered attributes as missing.**

Nothing recorded it either. The suggest-then-accept loop built for exactly this problem
(ADR-054, Phase 6.21b) is driven by `LayoutResolver`, which is never consulted for
attribute names — so the false finding recurred on every run of that delivery forever.

**Decision.** Two states that shared a code path are told apart by evidence, in one
place: `resolve/attributes.py`.

- **Missing** — nothing in the artifact resembles the wanted name. Still `passed=False`,
  still a high-severity violation. This is the finding the old code was written for.
- **Unresolved** — the ladder failed but candidates resemble the name. `passed=None`,
  plus an `attribute_not_resolved` record at `review` severity naming the closest
  candidates, so a reviewer can settle it.

Resemblance is three deterministic tests, all reproducible by a person reading the
workbook: the whole wanted name standing as one of the candidate's words, one squashed
name containing the other above a four-character floor, or a shared word of at least
three characters. The floor is not cosmetic — without it `ST` resembles `INCOME_EST`
(`st` sits inside `incomeest`) and a genuinely undelivered attribute would be softened
into a review record, trading a false positive for the far worse false negative. The
whole-word test is what carries a short name: `ST` standing alone inside
`debsc_burs_atyrt_st_1` is evidence where two buried letters are not.

**The shortlist only ever narrows.** It never picks: choosing between two plausible
candidates is the comparison ADR-001 keeps out of a guess's hands, and in 6.22d it is
what the model is shown.

**A second change this brought, which was not the stated goal.** Routing the three
callers through one helper routes attribute names through **the ladder**, which they had
never reached: they resolved on the alias table and `normalize_field_name` alone.
ADR-054 says one ladder resolves every name, and attribute names were the surface it was
never pointed at. So more resolves now than before, in code and with no configuration:
an OSL saying *score* reaches `SCORE_V3` on the token rung and *open trades* reaches
`OPEN_TRADES` on the squashed rung, where both previously needed a hand-written alias.
Nothing that matched before stops matching — the legacy lookup is tried first and still
wins — but the claim "only the severity changed" would be false, and the widening is
recorded here rather than discovered later.

What still needs an alias is what always did: a name no normalisation bridges, such as
the OSL's *revolving utilization* against a column called `REV_UTIL`. That is now the
case `tests/api/test_admin.py` uses to demonstrate the reference-data screen, because
the old demonstration resolves by itself.

**Consequences.** `attribute_renamed` goes from one high-severity violation to zero,
and `attributes_missing_in_report` still reports its genuinely absent attribute at high.
One helper answers "does this artifact carry this attribute" for all three callers, so
tolerance added for one reaches the others — which is how the three copies drifted apart
in the first place.

A run whose attribute names cannot be resolved still validates nothing about those
attributes; it is merely honest about it now rather than wrong. Resolving them is
Phase 6.22d, where the dictionary supplies the fourth rung and the model the fifth.

Two things this changed that were not the point. The `.gitignore` blocked `*.docx` and
`*.xlsx` outside `tests/fixtures/` but not `*.csv`, which ADR-003 plainly intends —
closed here because a record layout is exactly the file somebody drops in a working tree
to test with. And `scripts/seed_demo.py` appeared to write its alias rows transposed; it
does not. `canonical_by_alias` maps alias to canonical, so the loop's variable names
were simply the wrong way round and the stored data was always correct. The names are
fixed so the next reader does not reach the same wrong conclusion.

---

## ADR-060 — The record layout is a fourth artifact, uploaded per run and remembered per configuration

**Status:** accepted · 2026-09-21 · Phase 6.22b

**Context.** The tool reconciled three things: the OSL, the ETL config, and the output
reports. It had no account of the *delivered file itself* — which fields it carries, in
what order, at what type and size. Two consequences followed.

The first is the one 6.22a exposed: when the tool cannot work out what the DIRT calls an
attribute, it has nothing to look the name up in. It can only say so honestly, which is
what 6.22a made it do, and that leaves the requirement unevidenced. Five of
`attribute_renamed`'s requirements are unevidenced for exactly this reason.

The second is quieter and worse. A field that was ten characters and is now nine
produces no finding at all — there is no rule about it and nothing to compare against —
while it is the first thing the customer's loader notices.

**Decision.** A **record layout** is an artifact the tool accepts: one row per delivered
field, with the field's name, its data type and its size, where the field name is what
appears as the DIRT column. Five things follow from that and each one is a decision.

**It is optional, and stays optional.** `record_layout` is a built-in `artifact_types`
row with `is_required=False`. A delivery that uploads none is checked exactly as it was
before the slot existed, and every caller is written so that path is the ordinary one
rather than a degraded one — the same discipline `LayoutResolver` follows for a run with
no client.

**It is a fourth *kind*, not a report.** `parsers/base.NON_REPORT_KINDS` is now the one
place that says which uploaded kinds the pipeline does not read as report workbooks;
the worker, the replay and the credit-date pre-flight all read it rather than each
carrying their own `{"osl", "config"}`. Reading a schema with a report parser would put
a phantom report type into coverage and send every cross-report check looking for values
in a file that has none.

**Its own headers go up the ladder.** `parsers/record_layout.py` resolves *Field name*,
*Data type* and *Size* through `resolve.ladder`, with alternates for the words a source
system actually uses — *Column Name*, *Type*, *Length*. A parser that insisted on one
spelling would report a delivery as declaring no fields at all, which is the loudest
possible wrong answer and exactly the failure ADR-054 exists to prevent. A workbook with
no field-name column anywhere is a `ParseError` and **not** an empty layout, because
reading it as empty would assert "this delivery declares no fields" — the same
conflation of *absent* with *unknown* that ADR-059 undid.

**It is uploaded per run and remembered per configuration.** The same order delivered
next month has the same shape unless somebody changed it, so the layout is snapshotted
onto the run at stage 1 and **promoted onto the configuration at finalize**. Promotion
at finalize rather than at submission, for the reason the anomaly baseline uses the same
rule (Phase 6.21c): a layout nobody has signed off is not yet this configuration's
shape, and promoting earlier would let a mistaken upload become the baseline the next
delivery is judged against. A run that uploads none borrows the promoted layout, and the
borrowing is never silent — `runs.record_layout_run_id` and
`runs.record_layout_source_date` record it, `RecordLayoutDocument.provenance` renders it,
and every finding resting on a borrowed layout carries that clause. A borrowed layout is
never re-promoted, because that would move the source run forward to a run that uploaded
nothing and make the provenance untrue.

**It feeds the drift card.** `drift.diff_record_layout` reports fields added, removed,
retyped, resized and moved, matched on the name **up the ladder** so a respelling is not
reported as one field lost and another gained. Empty when either delivery carried no
layout, because "unknown" is not "unchanged".

**Consequences.** The run's snapshot is a copy, not a pointer, for the same reason the
configuration notes are copied (ADR-024): the promoted layout moves on and a finalized
report has to keep reproducing. `VersionKind` gains `record_layout`, keyed
`customer|configuration_id`, so a promotion can be reverted like any other definition —
and the version snapshot deliberately excludes the source run, because what is versioned
is the *layout*, and a second delivery of the same shape is not a new version of it.

This part adds no check of its own. What the layout lets the tool assert is 6.22e; what
it lets the tool *resolve* is 6.22f, where its field names become the suggestion a person
accepts into the dictionary.

Two things this changed that were not the point. `drift_out` never filled `record_layout`
— nor `newly_unchecked`, which has been computed since Phase 6.11c and had never reached
a screen; both are filled now. And `announcements.validate` counted its limit against the
wall clock, which is why `test_a_sixth_notice_is_refused_with_the_reason` was green the
morning it was written and red that afternoon; the moment is an argument now, as
`showing_now` has always taken one.

---

## ADR-061 — A product code is expanded by code; the model only reads that one was named

**Status:** accepted · 2026-09-21 · Phase 6.22c

**Context.** An OSL states the same requirement two ways. It either lists the fields —
*"deliver AT01, AT02, ST"* — or names a product code that stands for them — *"deliver
all attributes from ABC"*. The second form is how real orders are written, and the tool
had no account of it at all: the extraction had nowhere to put a code, so a requirement
stated that way either vanished or became an `attributes` requirement with an empty
value list, which is a requirement that asks for nothing.

**Decision.** A **product code** is reference data an administrator enters — a code, a
set of member attributes, and a scope — and the expansion from one to the other happens
in **code**.

**The model's only job is reading that a requirement names a code.** That is reading
meaning, which is exactly what ADR-001 gives it. Looking the code up, deciding which
attributes it contains, and checking that the code exists at all are lookups and
comparisons, which ADR-001 keeps in code. A model asked *"what is in ABC?"* answers
plausibly and is believed, and a delivery is then validated against a list nobody wrote.
So `ExtractedRequirement.product_codes` carries strings the model quoted, and
`ProductCatalogue` is what decides whether those strings name anything.

**An unknown code is a finding, never an empty expansion.** This is the decision the
whole part turns on. Expanding a code the catalogue does not define to an empty
attribute list turns *"check everything in ABC"* into *"check nothing"*, and the
delivery passes — for the worst possible reason, that the tool could not say what was
asked for. `unknown_product_code` is its own derived check, and it **fails** rather than
degrading to "could not evaluate": the tool knows exactly what is wrong and exactly who
fixes it. An administrator adds the code.

**Expansion happens once, at the end of stage 2, into `rule.values`.** Not at each
check. A requirement that names a code and one that lists the same attributes state the
same thing, so every stage after extraction must see the same rule for both — stage 5
comparing it with the config, stage 6 deciding whether a config element is covered,
stage 7 checking the reports. Expanding only where a check happens left the reverse pass
calling a correctly implemented config element *extra*, which is how this was found. The
codes stay on the rule after expansion, because they are what the unknown-code check
reports on and what the "beyond the code" note measures against.

**An attribute two codes share is one term with one output name.** If ABC and DEF both
carry `SCORE_V3` they carry the same one, delivered under one name. A catalogue where
they disagree is a defect, not two opinions: the console refuses the save that would
create one, and `ProductCatalogue.conflicts` names any that exist rather than picking a
winner — the same rule the ladder follows when two candidates tie.

**Carrying more than the code lists is a low-severity note and never a failure.** A
delivery may legitimately carry a technical field, and a tool that failed a correct
delivery over one teaches people to stop reading its findings. It is raised for two
reasons rather than one, and says both: the extract may have pulled more than the order
asked for, and **a field nobody asked for may be personal data that should not have
left** (ADR-003). It is silent unless a requirement actually names a code, because
without one there is no authoritative list of what was asked for and every unlisted
column would be "extra" on every run.

**The catalogue keeps no history; the run keeps a snapshot.** `Run.product_code_attributes`
holds the catalogue as it stood at submission, which is what makes a finalized report
reproduce — the same reasoning as ADR-024 for configuration notes and Phase 6.22b for the
record layout. A re-check expands from the snapshot, and when the live catalogue has
since moved it says so in a run notice: the catalogue cannot show *what* changed, but the
run must not quietly reproduce an answer an administrator has moved on from.

**Consequences.** `Rule.product_codes` sits beside `values`, and the `attributes`
requirement is the one set type that may carry codes instead of values — every other
still requires its values, because only attributes have a catalogue to be expanded from.
The extraction prompt goes to version 4. Codes are scoped with the ADR-037 vocabulary,
narrowest first, because one customer's `ABC` is not another's.

**Phase 7 refines this**, and only Phase 7 can: how a product code is recognised in real
OSL prose, and what real deliveries carry beyond their code, can be tuned against real
files and nothing else.

---

## ADR-062 — The attribute dictionary is tables, read as the ladder's fourth rung

**Status:** accepted · 2026-09-21 · Phase 6.22d

**Context.** Rung 4 of the resolution ladder has existed since Phase 6.21a and has never
had anything to read. It takes `alternates` — *other names that also mean this one* —
and the only caller that ever filled it was the layout map: sheet names, column headings
and row labels, a handful per artifact, in a JSON column on `artifact_types`.

Attribute names are the reason the rung was built and the one thing it has never
covered. 6.22a made the tool honest about it — an attribute it cannot locate is a
`review` record naming the closest columns, not a high-severity violation — and honest
is where it stopped. Five of `attribute_renamed`'s requirements stay unevidenced,
correctly, because nothing tells the tool that `debsc_burs_atyrt_at01_1` is `AT01`.

`design.md` has carried the matching open question since Phase 0: *"Is there an
attribute data dictionary to seed the alias table?"*

**Decision.** An **attribute dictionary**: `attribute_terms` (one canonical attribute,
scoped with the ADR-037 vocabulary) and `attribute_spellings` (one row per way an
artifact writes it, with provenance). It compiles into rung 4 and changes nothing about
`ladder.py`.

**Tables, not a JSON column.** `checks/layout.py`'s entries keep sheets, columns and row
labels and do **not** grow an `attribute` kind. A credit bureau's vocabulary runs to
thousands of attributes, each with a spelling per artifact and provenance on each
spelling; that is not a JSON column, and pretending otherwise would make every run load
a blob to answer one lookup. `resolve/layout.py`'s *kinds* do gain `attribute`, because
an attribute name reaches the same five rungs as a sheet name and what the model had to
reason about is offered to a person the same way.

**Provenance is on the spelling, not the term.** An administrator typed it, a record
layout declared it, the fifth rung reached it and somebody confirmed it, or a reviewer
proposed it. It is the *spelling* somebody vouched for.

**It never picks.** The dictionary hands the ladder alternates; the ladder decides, and
it still refuses when two candidates tie. A dictionary entry is a stronger claim than
any amount of normalising — which is why it is rung 4 and not rung 1 — but it is
evidence offered to code, not a verdict. One name means one attribute: the console
refuses a spelling another term already claims, because two terms claiming it would
leave the ladder unable to answer the question the dictionary exists to settle.

**A deterministic shortlist before any model call.** Rung 5 for an attribute is shown
`near_names`' handful, never a column dump — and then only what the dictionary cannot
already rule out, because a candidate it assigns to a *different* term is a distraction
somebody has already answered. Ruling out everything gives the candidates back
unchanged: an empty shortlist tells the model nothing and would turn a narrowing into a
refusal the caller never asked for.

**The cap is soft.** `llm.max_attribute_calls_per_run` bounds what rung 5 may cost, and
past it the resolver stops asking, the run records the names it did not look for, and
nothing is refused. No delivery fails over a budget; the checks that needed those names
have already said, separately, that they could not be evaluated. The precedent is
`s6_reverse._may_locate`. `runs.attribute_locate_calls` counts what was actually spent,
so the number can be measured rather than claimed — and so the second run of a
configuration whose spellings were recorded can be *shown* to have spent none.

**`attribute_aliases` is superseded by a dual-run read, not a migration.** The alias
rows are read alongside the dictionary on every run, the dictionary's own terms first.
Nothing that matched before stops matching. An explicit, previewed copy is offered in
the console for whoever wants to tidy up, and it adds and never removes — rewriting a
table an administrator seeded is not something to do behind their back, which is the
same reasoning ADR-037 gives for not rewriting stored scope strings.

**Consequences.** The two dormant hooks are populated at last.
`NamedValue.label_alternates` has been threaded from the pointer to `ReportSheet.lookup`
since Phase 6.15 with nothing ever putting a value in it; the dictionary fills it, so a
pointer whose label names an attribute finds it under whatever this delivery calls it.
`ReportSheet.resolve_column`'s `alternates` is filled the same way.

`present()` takes a resolver through a **Protocol** rather than an import.
`greenlight_ai.parsers` uses this package for its normalisers, and `LayoutResolver`
reaches `greenlight_ai.llm`; importing it would drag a model adapter into every parser.

**A silent defect this uncovered.** `context.resolver` was never assigned. Stage 7 built
a resolver in a local variable and `repository.save_context` read `context.resolver`,
which was always `None` — so **every run since Phase 6.21b has stored an empty
`layout_suggestions` list**, however much the model had to reason about. The
suggest-then-accept rail ADR-054 describes has never once been offered something a real
run found. Stage 7 assigns it now, which is also what makes `attribute_locate_calls`
reach the database.

---

## ADR-063 — A run's states are a closed set, and `draft` is one of them

**Status:** accepted · 2026-09-21 · Phase 6.23a

**Context.** `runs.status` is an unconstrained `String(30)` whose docstring listed
`held · queued · running · needs_review · finalized · failed`. The code also writes
`cancelled` (when a run is withdrawn before it starts) and `draft` (when a run is
cloned), so the register of states was two short of the truth. The browser knew better
than the database: `user-ui/lib/types.ts` has carried all eight in its `RunStatus` union,
with a badge tone and a label for each, since before either was documented.

Two lists of states is how a screen comes to render one it cannot name, and how a guard
comes to be written for the six somebody remembered.

**Decision.** `models.RUN_STATUSES` is the whole set, in lifecycle order, beside
`RETENTION_DAYS`. `ACTIVE_STATUSES` and `TERMINAL_STATUSES` name the two groupings code
actually asks about. The `Run.status` docstring says what each one means, including that
a `draft` is a run whose fields and artifacts can still be edited and which expires on a
shorter window than the retention one.

**Deliberately not a database `CHECK` constraint.** ADR-017 requires migrations portable
across SQLite and Postgres, and a `CHECK` on this column means a `batch_alter_table`
rebuild every time a state is added — for a column that has carried eight without one.
What keeps it honest instead is that every write site uses a name from the tuple, and a
test reads `user-ui/lib/types.ts` and asserts the two languages name the same eight
states. A status added on one side and not the other now fails the suite.

**Consequences.** A guard can be written against the set rather than against the states
somebody happened to recall, which is what ADR-066 does. The remaining work of Phase 6.23
— the endpoints that let a draft be edited, submitted or discarded — has a documented
state to attach to rather than a string the code invented.

---

## ADR-066 — A re-check belongs to review, and a frozen report stays frozen

**Status:** accepted · 2026-09-21 · Phase 6.23a

**Context.** `POST /runs/{id}/recheck` had no status check at all. It read the run and
enqueued the task. That accepted a `draft` with no files, a `queued` or `running` run the
pipeline already owns, a `failed` or `cancelled` one with nothing to re-compare — and a
**finalized** one.

The last is the serious one. A re-check rewrites rules, traces and findings wholesale.
Re-reviewing a finalized run is refused by the findings route, the coverage routes and
the report route, because hard rule 5 and ADR-005 say a frozen report must keep matching
what the reviewer was shown. The re-check route was the hole in that: the `FinalReport`
row stayed frozen while everything it described was replaced underneath it.

Two smaller faults sat beside it. A re-check runs stages 5 to 7 and skips stage 9, but
`save_context` wrote `run.summary` and `run.top_issues` unconditionally from a context
whose defaults are empty — so **every re-check erased the plain-English account of the
run**, and a reviewer lost the narrative in the act of correcting one rule. And
`gate_state` computed `can_finalize` from undecided findings, unacknowledged requirements
and second approvals alone; a run with none of any passed every test vacuously, so an
empty draft was reported as ready to freeze, under a tooltip claiming every
high-severity finding had a decision. The same was true of a queued, running, held,
failed or cancelled run.

**Decision.** One condition, applied at both places that queue a re-check — the
standalone endpoint and the requirements edit that queues one of its own:

> `run.status != "needs_review"` → 409, naming the status.

It is deliberately a whitelist of one rather than a blacklist of `finalized`. A re-check
compares an existing set of rules and traces against parsed artifacts; the only state in
which that is a meaningful question is the one where a person is reviewing the answer.

`save_context` gains an explicit `narrative` flag, passed `False` by the re-check — not
an emptiness test, because a run that genuinely summarised to nothing should still be
able to record that. And `gate_state` answers for the whole run before it counts
anything: a run that never reached review cannot be frozen, and says so. Fixing it there
rather than on the button made the header, the report page's card and the coverage card
truthful at once; patching the button would have corrected one of five screens telling
the same untruth.

**Consequences.** The standalone Re-check control is removed in 6.23b — it is documented
nowhere, gives the user no visible feedback, and its only documented use case is already
automatic, because editing a requirement queues the re-check itself. The endpoint stays,
because `design.md` documents it and it is now safe.

This does not amend ADR-054's account of what a re-check costs. It narrows when one may
be asked for at all.

---

## ADR-064 — One submission body, whichever door a delivery came through

**Status:** accepted · 2026-09-21 · Phase 6.23c

**Context.** `POST /runs` was 267 lines doing seven jobs: read the multipart form, check
the per-order queue limit, check the start-rate window, check the tool is accepting
work, store the files, fingerprint them against ADR-005, and either hold or queue the
run. A draft being submitted has to do six of those seven — everything but reading the
form, because its files are already stored.

Writing that second path as a second copy is how the two would come to admit different
deliveries: somebody adds a check to one, and a delivery's fate starts depending on
which screen it was submitted from.

**Decision.** Four helpers — `_read_uploads`, `_admit`, `_store_uploads`,
`_finish_submission` — and both endpoints are assembled from them.

The non-obvious part is an ordering change. `RunFile` rows are now written **before**
the fingerprint is computed, where they used to be written after the duplicate branch.
That is what lets everything downstream answer "what files does this run have?" by
reading `run.files` rather than a list only the create path holds, and it is why
`_record_mismatches`, `_capture_config_from_upload` and `_labelled_credit_date` now take
`RunFile` rows instead of freshly stored tuples.

**One deliberate divergence between the two paths**, expressed as an argument rather
than a branch: `discard_on_duplicate`. `POST /runs` deletes the run it built seconds ago
when the inputs match an earlier one and no reason was given — it is a throwaway. A
draft is not: it holds fields somebody typed and files somebody uploaded, and deleting
it would destroy that work in the act of asking a question about it. So the draft
survives, the person supplies a reason, and they press submit again.

**And the dialog now knows what it is looking at.** When the run the fingerprint matched
*is* the draft's `cloned_from_id`, the message says so — *"this is a clone of run N and
its files are unchanged"* — rather than "these inputs were already run", which reads as
nonsense to somebody who believes they just uploaded them. That is the commonest way to
reach this dialog: clone, correct a field, forget to swap the DIRT. It is also the first
thing in the product ever to read `cloned_from_id`, which had been written and never
looked at since Phase 3.

**Consequences.** The start-rate window now excludes drafts. It counts runs by
`created_at`, and once a draft can sit for five days an old one would otherwise consume
a window it never used. `uploads.max_mb` is read for the first time as well, because
every upload now goes through one helper that resolves it.

---

## ADR-065 — A draft expires in five days; one column, and the status picks the window

**Status:** accepted · 2026-09-21 · Phase 6.23c

**Context.** A cloned draft was stamped with the ordinary retention window, so an
abandoned one sat in the runs list for ninety days having validated nothing. Drafts
needed a shorter life, and an administrator needed to set it.

`retention.days` was the obvious model to follow, and it turned out to be broken:
`expiry_from`'s `days` parameter was never passed by either caller, so the window was
always the import-time constant however the console was set — and the console showed a
warning dialog when you shortened it. `uploads.max_mb` had the identical defect. Both
appeared in `src/` only in their own registry declarations.

**Decision.** `repository.expiry_for(session, run)` resolves the window at the call site
(ADR-023), choosing `retention.draft_days` when the run is a draft and `retention.days`
otherwise.

**One column, not two.** `status == "draft"` already *is* the fact that says which
window applies, so a second column would only give the purge two predicates and ADR-023
two settings that can disagree.

**The stamp is taken once and never recomputed.** A run is stamped at creation, and a
draft is re-stamped from `utcnow()` when it is submitted — from now, not from when it
was cloned, because a draft sat on for four days must still get its full retention once
it becomes real work. Nothing else ever rewrites it. That is the whole safeguard:
changing either setting affects only rows created afterwards, so a shortened window
cannot delete work that already exists. It also means `retention.days`'s help text —
*"Shortening it deletes more at the next sweep"* — was false, and has been corrected.

**Consequences.** The existing 24-hour worker sweep deletes an expired draft unchanged;
no new scheduler, no cron. It counts and audits abandoned drafts apart from runs that
reached the end of their retention, because a draft leaving silently (the user's
decision) is not the same as one leaving unrecorded.

A draft submitted into `held` is re-stamped **before** the mismatch branch, not after.
Found while building: taking the early return left a held run on the five-day window
while it waited for somebody to accept the disagreement, which would have purged it out
from under them.

---

## ADR-067 — A re-check is asked for by an edit, and the queue is what says it is running

**Status:** accepted · 2026-09-21 · Phase 6.23b

**Context.** The Review screen had a **Re-check** button that re-ran stages 5–7. Nothing
documented it — no tooltip, no Guide entry, no phase note; its own docstring was the only
description of it in the repository — and every document that mentions a re-check describes
exactly one case: *edit a requirement or a trace link, then re-check*. Pressing it with no
edit behind it re-compared inputs nobody had changed, and because a re-check changes no
status, the screen did not move: the user clicked, the button flickered, and the rebuilt
findings appeared only on a manual reload.

Removing it exposed something worse. `PUT /runs/{id}/requirements`, the endpoint that queues
the re-check *as part of the edit*, **had no caller in either app**. `design.md` has promised
*"Edit a requirement or a link, then Re-check"* since Phase 2 and `user-training.md` told
people to do it. Nobody could.

**Decision.** A re-check is asked for by an edit and by nothing else in the product.

**The edit exists now.** A matrix row offers **Fix link**: choose the right configuration
element, or *Linked to nothing* when the configuration genuinely does not implement the
requirement, and give a reason. The reason is required — a correction without one is
indistinguishable months later from a misclick, and the trace stores who made it. A
finalized run refuses it under the same guard as the re-check (ADR-066), because it is the
same act.

**`POST /runs/{id}/recheck` stays on the API.** `design.md` documents it and 6.23a guards it.
Removing a documented endpoint to delete a button is a different change, and an operator
re-running the comparison stages deliberately is not the confused click the button invited.

**Visibility is the queue's answer, not a ninth status.** A re-check leaves the run in
`needs_review` by design: it rebuilds findings and changes nothing else. A `rechecking`
status would have made the fact visible in a vocabulary that `RUN_STATUSES`, the TypeScript
union, every status filter, both label maps and both tone maps would have to learn — for a
job that takes seconds and for a state no report, gate or audit line needs to distinguish.
`JobQueue.pending_for(run_id, task)` asks the queue instead; `RunDetail.rechecking` carries
the answer; the screen polls on it and reloads its findings on the edge where it clears.

**Consequences.** A failed re-check leaves the run's status alone. Its findings are rebuilt
from rules and traces that are already stored, so a run awaiting review still holds
everything it had when the job was claimed — marking it `failed`, or `queued` while a retry
was pending, took a reviewable run away from the person reviewing it and no retry gave it
back. The job is still marked failed and the error is still recorded on the run, so nothing
is silent; only the status is untouched, and only for this one task.

The ADR-054 guard moved to the path that runs. `worker/runner.py::recheck_run` counted rows
in the call log, so every correctly-cached re-check logged a warning; it counts tokens now,
as the unreached copy in `pipeline/run.py` already did.

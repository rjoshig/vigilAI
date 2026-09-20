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


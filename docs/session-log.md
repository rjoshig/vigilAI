# Session Log

Working journal. **Read the "Resume here" block first at the start of every session; update
it and append an entry at the end.** Required fields per entry: branch, phase, status,
what was completed, what's pending, blockers, next concrete action. No PII, no customer
names, no sample data.

---

## Resume here

| Field | Value |
| --- | --- |
| Phases complete | **0–5**; **6 in progress**; **6.1 and 6.2 specified and decided, not started**; **7 dormant** (runs only on request) |
| Branch | `claude/funny-cerf-jsyvpe`, pushed to `origin` |
| Last updated | 2026-09-18 |

**The product is built and works end to end.** Submit an OSL, a config, and the
reports; the worker runs the nine stages; a reviewer decides each finding; the frozen
one-page report is generated once and never regenerated.

### See it running

```bash
source .venv/bin/activate
export DATABASE_URL="sqlite+pysqlite:///$PWD/data/demo.db" VIGILAI_DATA_DIR="$PWD/data"
python scripts/seed_demo.py          # 8 runs in every lifecycle state + admin data
uvicorn vigilai.api.app:get_app --factory --reload   # :8000
python -m vigilai.worker.app                          # another terminal
cd user-ui && npm run dev                             # :3000
cd admin-ui && npm run dev                            # :3001
```

`scripts/seed_demo.py` loads the aliases, the artifact catalog with five sample
workbooks and one worked example of AI context, the design doc's three example checks,
the compliance rules, and runs sitting at queued, needs review, finalized OK, finalized
Not OK, and failed.

The user-ui sidebar now carries an **Admin console** launcher
(`NEXT_PUBLIC_ADMIN_URL`, default `http://localhost:3001`), so the two apps are one
click apart in development.

**Gates:** `black . --target-version py310 && flake8 && mypy src/ && pytest &&
bash scripts/check_docs.sh`, and in each UI: `npm run lint && npm run typecheck &&
npm run format:check && npm test && npm run build`.

### Phase 7 is written but dormant

[`phase-7.md`](phase-7.md) is the phase for the machine that holds the real files
(ADR-019). It runs **only when you ask**, one artifact at a time: *"look at this OSL and
tell me what needs to change"*. It carries the per-artifact tables of what the parsers
assume today and what would break each assumption, so the analysis starts from the code
rather than a blank page. Its first rule is that no real file, and nothing derived from
one, enters this repository.

### Phase 6.1 is specified and waiting on six answers

[`phase-6.1.md`](phase-6.1.md) covers richer inputs (up to three samples per artifact
type, several files per report type, workbook type detection, delivery counts) and
**Train AI mode**: reviewers record anchored observations in their own words, an
administrator has the model synthesize them into candidate rules, and an approved rule
runs in shadow before it counts. ADR-021 holds the shape and is **proposed**, not
accepted, because six open questions at the foot of the phase doc change the design.
Answer those first.

### Next: build Phase 6.2, then Phase 6.1

Sixteen design questions across both phases were answered on 2026-09-18 and are
recorded in the **Decisions** table of each phase doc. ADR-021 and ADR-022 are
accepted. The user chose to **build 6.2 first**, so the training loop is attributed to
real people from its first day rather than retrofitted.

The load-bearing answers: the API refuses to serve on the default password off
loopback; sessions last eight hours with an hour idle; twelve-character minimum and
lockout, no complexity rules and no expiry; with login off everything is attributed to
the placeholder and there is no free-text name box; single sign-on is expected
eventually and the session table is shaped for it. On the training side: a learned
rule starts at the narrowest scope that fits, anyone may file an observation under
their name, an administrator activates a shadowed rule with the numbers shown rather
than a fixed threshold, replay reads the golden set plus recent finalized runs,
observations are kept indefinitely, and authors hear the outcome with a reason.

One question is still open: whether a learned rule ever expires.

### Phase 6.2 (specified 2026-09-18)

[`phase-6.2.md`](phase-6.2.md) adds login that **ships off**. Two `.env` switches, one
per app. An administrator creates every account; there is no self-registration. The
design turns on one idea: **there is always a current user**, a seeded placeholder
while login is off, so nothing stores a nullable author and no handler branches on
whether authentication is enabled. ADR-022 amends ADR-008 and is **proposed**, not
accepted. The bootstrap credential is `admin` / `admin123` as requested, with a forced
change at first sign-in; whether production should refuse to serve until it is changed
is one of the open questions.

### Outstanding, needs the user

- **Merge the Phase 0 PR and create `dev` from `main`.** Eighteen commits are stacked
  on one session branch. This is the thing to do first.
- **A decision on retention for DIRT files** (90 days by default), and **security and
  compliance sign-off** on retention and PII handling. Both are Phase 6 criteria and
  both want an ADR.
- **A local model** or an API key: `python scripts/golden_set.py --provider openai
  --out docs/benchmarks/phase-2.md` closes Phase 2 criterion 2 and Phase 6 criterion 2
  in one command. Expect a prompt-version bump afterwards.
- **A sanitized shape reference** for the real OSL, config, and report layouts. The
  parser Protocols exist so this is the only code that changes, but every layout
  assumption today came from synthetic fixtures.
- **On a machine with Docker:** `docker compose up --build` once (Phase 3 criterion 1).
  This is the last unverified criterion in Phases 0–5.
- Whether a data dictionary exists to seed the alias table from.

---

## Session: 2026-09-18 (design questions answered; ADR-021 and ADR-022 accepted)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.1 and 6.2 (specification) ·
**Status:** decided, nothing built.

### What was completed

- Sixteen open design questions put to the user and answered. Each phase doc now
  carries a **Decisions** table in place of its open-questions list, and both ADRs
  moved from proposed to accepted.
- Two answers went against the recommendation and are recorded as chosen, not as
  suggested: **an administrator activates a shadowed rule by judgement** with the
  numbers shown, rather than passing a fixed sample-and-precision bar, because a
  rarely-firing rule would otherwise wait forever for a sample it never gets. And
  single sign-on is **expected**, so the session table is shaped to accept an external
  provider.
- Build order set by the user: **6.2 first, then 6.1.**

### Pending

- Everything in both phases; they are specified and decided but unbuilt.
- One open question: does a learned rule ever expire?

### Blockers

None. Phase 6.2 can start.

### Next concrete action

Build Phase 6.2 milestone 6.2a: give `current_user()` a real body, seed the
placeholder account, and add the `admin_required` dependency, with both switches
defaulting to off so the existing suite passes unchanged.

---

## Session: 2026-09-18 (Phase 6.2 specified — optional login and attribution)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.2 (specification only) ·
**Status:** documented, nothing built.

### What was completed

- `docs/phase-6.2.md`: six milestones. One identity whether or not login is on;
  accounts an administrator creates with a forced first-sign-in password change;
  server-side sessions with revocation; attribution on runs, reviews, config history,
  and the frozen report; the append-only training record; docs and tests.
- ADR-022 (**proposed**), amending ADR-008: login exists, ships off behind two
  independent switches, and there is always a current user.
- The seam ADR-008 left turns out to be sufficient. `api/deps.py` already defines
  `CurrentUser` and `current_user()`, and every router already depends on it, so the
  API change is one function body plus a session table and actor columns.
- The user's record-keeping rule is written down explicitly: synthesis **marks** an
  observation as synthesized with its date and target and never consumes or deletes
  it, and re-synthesis produces a new candidate rather than editing the old one.

### Pending

- The five open questions at the foot of the phase doc, chiefly whether production
  should refuse to start while the bootstrap password stands.
- Phase 6.1's six open questions, still unanswered.

### Blockers

None.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 6.1 specified — richer inputs and a trainable rule loop)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.1 (specification only) ·
**Status:** documented, nothing built.

### What was completed

- `docs/phase-6.1.md`: eight milestones covering up to three samples per artifact type
  with view and download, several files per report type with per-part findings,
  delivery counts that code verifies, workbook type detection that is deterministic
  first and asks when unsure, and the training loop.
- ADR-021 (**proposed**): observations are anchored to a cell, clause, or config path
  rather than being prose alone; suggested and active are different states; the model
  emits a schema-constrained rule object and has no authority to write or activate;
  candidates are replayed against the golden set and recent runs before approval; an
  approved rule runs in shadow until its dismissal rate earns activation; provenance
  includes the diff between the model's draft and the approved rule.
- Prior art surveyed and recorded in the phase doc: Great Expectations, Soda, Deequ
  constraint suggestion, dbt, and the suggested-monitor products. They agree on the
  point that matters — machine-suggested rules never auto-promote.
- `scripts/update_phase_status.py` now globs `phase-[0-6]*.md`, so 6.1's markers are
  derived and checked like every other phase. Glossary, phase-plan, CLAUDE.md, and
  README updated.

### Pending

- The six open questions at the foot of the phase doc. Each becomes an ADR, and
  ADR-021 cannot move from proposed to accepted until they are answered.

### Blockers

Nothing technical. The design is decided enough to build once those answers land.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (admin-configurable artifact types and run scope — ADR-020)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** amendment to Phase 4 · **Status:**
complete, all gates green.

### What was completed

- **The catalog left the code.** `ReportKind` is an open string with the built-ins
  listed; an unknown key is read by `GenericReportParser`. `artifact_types` replaces
  `report_templates` and covers the OSL and the config as well as each report, each
  with a label, a description, a sample workbook, an `ai_context` field, and active and
  required switches. `run_scopes` holds AM, AS, Archives, and a catch-all with standing
  instructions; a run records its scope and a suppressions answer defaulting to no.
- **Guidance is additive.** `pipeline/guidance.py` builds a preamble that labels itself
  background rather than requirement, and returns an empty string when nothing is
  configured, so a fresh install sends the prompts it always sent. The preamble is part
  of the rendered prompt, so editing guidance invalidates exactly the affected cache
  entries and nothing else.
- **The new-run form is generated** from `GET /runs/options`: dynamic upload slots, a
  programme dropdown, and a suppressions radio defaulting to No. admin-ui gained the
  **Artifact types** and **Delivery programmes** screens, and `/templates` is gone.
- **The user-ui sidebar gained an Admin console launcher**, at the user's request.
- Migration `7055ed7523c8`, 26 new tests, ADR-020, and the design, architecture,
  phase-4, phase-7, and README updates.

### The bug worth remembering

`fastapi.UploadFile` is a **subclass** of `starlette.datastructures.UploadFile`, and
`request.form()` yields the Starlette one. Reading the report uploads dynamically meant
an `isinstance` check against the FastAPI class, which silently matched nothing and
dropped every report, surfacing as "at least one output report must be uploaded" on a
form that plainly had them. Test against the base class.

### Pending

- The demo services were running against a database that predates `artifact_types`;
  reseed before the next walkthrough.
- Everything under "Outstanding, needs the user" above.

### Blockers

None.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 1 — UI mock built)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 1 · **Status:** mock complete,
walkthrough pending.

### What was completed

- Restructured `ui-mock/` → `mock/` with `shared/`, `user-ui/`, `admin-ui/` (ADR-013),
  at the user's request, so the two apps are separate mocks.
- `mock/shared/styles.css` (ui2 tokens: light, dark, and the active `light-blue-yellow`
  palette) and `mock/shared/app.js` (sidebar, icons, theme, toast, tabs, modal, drawer).
- user-ui: Runs (live stage progress, queue position), New run (drop zones, copy from
  previous, duplicate-inputs dialog with required rerun reason), Review (traceability
  matrix, findings with OK / Not OK + comments, bulk-OK low, evidence drawer with masked
  sample rows, edit requirement / link modals, waterfall with breaks, attribute explorer,
  Generate gated on High decisions), Final report (frozen, PDF, clone), Run stats, Config
  history (view JSON, copy into new run).
- admin-ui: Report templates + named values, Checks (describe → propose → test →
  activate; judgment flagged "use sparingly"), Compliance & reverse-pass scope,
  Reference data (aliases, masked columns), Usage.
- Docs: phase-1 checklist ticked (criteria 1–3), phase-plan, README, standards, CLAUDE.md
  point to `mock/`; ADR-013 added.
- Verification: `node --check` on all scripts (shared + inline) clean; PII-pattern grep
  clean; launcher rendered in headless Chrome and looked right. Per-page headless
  screenshots could not be captured (Chrome hung on repeat launches), so the pages have
  not been visually checked in a browser yet — the user's walkthrough is that check.

### Pending

- Stakeholder walkthrough (acceptance criterion 4) and feedback capture.
- Phase 0 PR merge; creation of `dev`.

### Blockers

None for the walkthrough.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 0 — repo setup)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 0 · **Status:** deliverable complete,
PR opened.

### What was completed

- Settled the repo layout: CLAUDE.md as a router, `standards/`, `docs/` with the phase,
  ADR, and session-log conventions, the static mock, and the `ui2` frontend toolchain.
- Agreed with the user: branching main/dev/feature; CI manual-only; Python 3.10 floor +
  pin; ui2 stack + Vitest; compare-file docs layout + "Resume here" + glossary;
  `src/vigilai/` layout; `docker/` dir + root compose; one phase doc per design phase.
- Created the whole Phase 0 tree (see `docs/phase-0.md` scope). `docs/design.md` is the
  design doc verbatim.

### Pending

- Human review + merge of the PR; creation of `dev`.
- Phase 1.

### Blockers

None for Phase 1. The design-doc open questions block parts of Phases 2, 4, 6 (listed in
`docs/phase-plan.md`).

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2a)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2a complete.

### What was completed

- Phase 1 signed off by the user; ADR-014 (build against `LLM_PROVIDER=mock`, defer the
  Gemma benchmark) and ADR-015 (finalize gate = every High finding decided) recorded.
- Python 3.10.14 installed via pyenv; `.venv` created; Phase 2 runtime dependencies
  (pydantic, httpx, python-docx, openpyxl) added to `pyproject.toml`.
- `parsers/base.py`: `OslParser` / `ConfigParser` / `ReportParser` Protocols and frozen
  value objects (`OslSection`, `OslTable`, `ConfigBlock` with JSON path, `ReportSheet`
  with cell addresses and label lookup).
- `parsers/masking.py`: masked-column matching and value masking applied **at parse
  time**, so an unmasked value never exists downstream (ADR-003).
- `parsers/osl_docx.py` (document-order walk of headings, paragraphs, tables),
  `parsers/config_json.py` (logical blocks with JSON paths, technical-key classification),
  `parsers/reports/xlsx.py` (one class per report kind over one read-only reader).
- `scripts/generate_fixtures.py`: six seeded synthetic cases, each carrying its own
  oracle in `manifest.json` — baseline match, extra state, value mismatch, missing rule,
  missing attribute, counts not reconciling.
- 73 tests, 97% branch coverage. `black`, `flake8`, `mypy --strict`, `pytest` all clean.

### Notable decisions and fixes

- `check_docs.sh` was failing on `main` before this work (grep exit 1 under `pipefail`
  for any link-free markdown file); fixed.
- flake8-bugbear B042 on `ParseError` turned out to be a real defect: forwarding extra
  args to `super().__init__` broke unpickling. Fixed with `__reduce__` and a test, since
  the worker carries exceptions across a process boundary.

### Pending

2b (canonical rule schema and normalizers), then 2c–2f.

### Blockers

None. The real-file shape reference and a local model are still wanted but do not block
2b–2f (ADR-014).

### Next concrete action

Milestone 2b: `rules/schema.py`, `rules/normalize.py`, `rules/derive.py` with tests.

## Session: 2026-09-18 (Phase 2 — milestone 2b)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2b complete.

### What was completed

- `rules/schema.py`: Pydantic models for the canonical rule envelope (`Condition`,
  `Rule`), plus `ConfigElement`, `Trace`, `Evidence`, and `Finding`. Validators reject
  payloads that do not match their `req_type` and verdicts that claim an implementation
  without naming an element, so stage 5 needs no defensive checks. `extra="forbid"`
  stops a hallucinated key from passing validation.
- `rules/normalize.py`: state names to codes (all 50 plus DC and territories),
  `AliasTable`, `Interval` carrying boundary inclusivity explicitly, and `parse_number`
  for the forms specs actually use (`1,000,000`, `$40,000`, `60%`).
- `rules/derive.py`: derived report checks per operator, including the inversion that
  turns `age < 21 -> reject` into `accepts.age.min >= 21`.
- 165 tests, 98% branch coverage. All four gates clean.

### Notable decisions

- `Interval` keeps inclusivity separate from the bound because operator mismatch is its
  own finding type; `same_bounds_as` distinguishes a value mismatch from an operator one.
- An OR of conditions derives no report check: either branch may be satisfied, so neither
  bounds the delivered population. A wrong check would be worse than none.
- An unparseable condition value derives nothing rather than a guess; the rule is already
  visible as low-confidence.
- `AliasTable.resolve` returns the normalised input for an unknown name instead of
  raising, so an unknown attribute fails to match and becomes a finding.

### Pending

2c (LLM adapter, cache, prompts), then 2d–2f.

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2c)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2c complete.

### What was completed

- `llm/settings.py`: every knob from `.env`, validated at load time, failing with the
  offending key named.
- `llm/client.py`: the `LLMClient` Protocol, `LLMResult`, the typed error hierarchy, and
  `CallRecord` / `CallLog` (ids and counts only, no prompt text).
- `llm/cache.py`: key = sha256(content) + model + prompt version, with in-memory and
  SQLite backends behind one Protocol so Phase 3 can swap in Postgres.
- `llm/base.py`: the shared path every provider inherits — check the cache, enforce the
  run budget, send, recover JSON from fenced or prose-wrapped answers, validate against
  the schema, retry exactly once with the validation error appended, record the call.
- `llm/openai_compat.py`, `llm/anthropic.py`, `llm/mock.py`, `llm/factory.py`.
- `llm/prompts/`: registry plus five versioned templates (stages 2, 3, 4, 8, 9), each
  with two or three worked examples and a Pydantic output schema.
- 282 tests, 97% branch coverage. All four gates clean.

### Notable decisions

- Prompt templates use `$name` placeholders rather than `{}`: every prompt embeds worked
  examples of JSON output, and brace formatting treated those braces as placeholders.
- The cache key includes the output schema name. The same prompt asked for a different
  shape is a different call, and serving the old answer would return the wrong shape.
- Error messages never echo a response body. A provider's 4xx body can quote the prompt.
- The mock returns empty-but-valid payloads rather than invented requirements: a mock
  that fabricates findings would make a passing pipeline test meaningless.
- An autouse fixture blocks the socket layer for the whole suite. The injected transports
  prove the happy path; blocking sockets proves there is no other path.
- Prompt versions are provisional until the first real-model run (ADR-014); expect a bump.

### Pending

2d (stages 1–5), 2e (stages 6–9), 2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2d)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2d complete.

### What was completed

- `pipeline/context.py`: `RunContext` (the object a run threads through its stages),
  `StageRecord` per-stage status and timing, the re-check stage list, and the
  finalize-gate check (ADR-015).
- Stages 1–5: parse; extract requirements one OSL section per call; describe config
  blocks one per call with technical blocks classified in code and skipped; trace with
  a code-first shortlist and exact-match link, judge only for unclear pairs; compare
  sets, intervals with their operators, attribute lists, waterfall order, and quantities.
- `pipeline/run.py`: orchestrator recording status, duration, calls, cache hits, and
  tokens per stage; resume from the last good stage; `recheck()` reruns stages 5–7 only
  and asserts it makes no LLM call.
- 341 tests, 94% branch coverage, including the design doc's worked example end to end
  (OSL {IL, AZ} vs config {IL, AZ, TX} reports TX as extra) and a direct test for every
  comparison branch.

### Notable decisions and fixes

- ADR-016: waterfall order is compared on shared steps only. Comparing the lists
  literally reported a mismatch on every run, because a config's step list carries
  boundary markers the OSL never mentions.
- The judge prompt now always carries the element's type and payload, not just its prose
  description: "the processing order" does not tell a judge which requirement family a
  block belongs to.
- The stage 4 shortlist falls back to type-only when no field name matches, so a missing
  alias surfaces as a weak trace rather than masquerading as "no config rule".
- Building the fake judge exposed the same trap in test form: matching on `req_type`
  alone linked a score requirement to an age rule. The responder now discriminates on
  the attribute, as the real prompt instructs.
- A stage that fails records itself as failed before the error propagates, so the run's
  own record says where it stopped.

### Pending

2e (stages 6–9 and the expression evaluator), 2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2e)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2e complete; all
nine stages now run end to end.

### What was completed

- `checks/expressions.py`: a safe evaluator for admin-authored check expressions. Walks
  a parsed AST and permits only comparison, arithmetic, and four pure functions. No
  `eval`, no attribute access, no comprehensions, no `**`.
- `checks/named_values.py`: cell and label-lookup resolution, with number coercion for
  the forms report cells actually hold.
- `checks/definitions.py`: `CheckDefinition`, `ComplianceRule`, `ReversePassCategory`,
  and the shipped default categories.
- `checks/reports.py`: the fixed per-`req_type` report checks.
- Stages 6 to 9: scoped reverse pass plus compliance presence; report checks and admin
  expression checks; second-opinion verification; the summary.
- 475 tests, 94% branch coverage. All four gates clean.

### Notable decisions and fixes

- The report checks were resolving attribute names with plain normalisation, so a DIRT
  column named `SCORE_V3` never matched an OSL requirement about "score" and every
  bound check reported "could not evaluate". They now resolve through the alias table
  on both sides. This is the bug the alias table exists to prevent.
- `step_order` is not a report check. The counts report shows totals per step, not the
  order they ran in, and order is settled between the OSL and the config in stage 5.
  Treating it as a report check produced a spurious finding on every run.
- A disputed finding is downgraded to Review and kept, never dropped: the model may
  reduce false positives but must not be able to hide a real problem.
- A failed verification or summary leaves the run intact. Both are improvements on the
  findings, not gates over them.
- Admin configuration moved onto `RunContext` so the orchestrator can call every stage
  with one uniform signature; Phase 3 fills it from the database.

### Pending

2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2f; Phase 2 complete)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** complete except the
deferred real-model benchmark.

### What was completed

- `src/vigilai/cli.py`: `vigilai run` with `--osl`, `--config`, repeatable `--report
  KIND=PATH`, `--out`, `--provider`, `--cache`, `--stage`, and `--log-level`. Writes a
  findings document carrying the summary, per-severity counts, per-stage statistics,
  the finalize-gate state, and every finding with its evidence.
- `scripts/synthetic_model.py`: the scripted stand-in that answers each LLM stage by
  reading the prompt. Lifted out of the test conftest so the golden set and the suite
  drive the pipeline identically.
- Golden set expanded to 12 cases covering every finding type in the design doc's table,
  each carrying its oracle in `manifest.json`.
- `scripts/golden_set.py`: scores recall and precision per finding type and per case,
  writes a Markdown report, and exits non-zero on a regression so CI can gate on it.
- `docs/benchmarks/`: the synthetic baseline, 12 / 12 cases, and a README stating plainly
  what that number does and does not prove.
- 505 tests, 95% branch coverage. All four gates clean.

### Notable decisions and fixes

- The CLI exits 0 for a run that completes and finds problems, and non-zero only when
  the run itself fails. A wrapper has to be able to tell "the delivery is wrong" from
  "the check did not happen".
- A failed run still writes its document, carrying the stages that completed and the
  error, so a caller can see how far it got.
- `run_command` takes an optional client, which is the seam the golden set injects the
  scripted stand-in through. No fixture-aware code lives in `src/vigilai/`.
- The scripted model could not read a filter whose threshold is stored in `value`
  rather than `min`, which cost one golden-set case. Fixed in the responder, since a
  real model would read both spellings.

### Pending

Phase 2 acceptance criterion 2: the real-model golden-set run. Everything else is done.

### Blockers

The real-model run needs a local model or an API key from the user (ADR-014).

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (documentation currency pass)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** between 2 and 3 · **Status:** docs
brought current; no code change.

### What was completed

- Marked phases 0, 1, and 2 complete: every scope box and acceptance criterion ticked in
  `phase-0.md`, `phase-1.md`, and `phase-2.md`, with dated status lines. Two boxes stay
  deliberately unticked and are labelled: phase-0 exit criterion 6 (a human merges the PR
  and creates `dev`) and phase-2 acceptance criterion 2 (the real-model benchmark,
  ADR-014).
- Gave every phase doc and both master tables the same status vocabulary
  (⬜ not started · 🟡 in progress · ✅ complete).
- Removed every reference to the other repositories we looked at during setup. The
  decisions they informed are stated on their own merits in the ADRs; the provenance was
  noise that would age badly. `compare-file` survives only where it is a live
  instruction, such as the ui2 theme tokens the mock copies and the report format.
- Added the rules that keep this from drifting again, in `CLAUDE.md`: a "Finishing a
  phase" checklist, a "documentation is always current" rule, an instruction to grep for
  a name before renaming it, and two more steps in the definition of done (ADRs written,
  `check_docs.sh` passing, commit actually pushed).
- Recorded two more open questions in `phase-plan.md`: the waterfall step-name aliases
  that ADR-016 raised, and which model the golden set should be benchmarked against.

### Pending

Phase 3.

### Blockers

None for Phase 3. The items under "Resume here" need the user but do not block it.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 3 — web app)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 3 · **Status:** complete, with the
compose run unverified.

### What was completed

- **ADR-017**: `DATABASE_URL` selects the backend. SQLite is the default, so a test, a
  migration, or a single run needs no Docker; Postgres is what compose configures.
  Procrastinate is dropped — it is Postgres-only — and the queue is now an ordinary
  `jobs` table. That removed a dependency rather than adding one, and there is still no
  Redis.
- `db/`: all 21 tables, portable column types, session helpers with the SQLite pragmas
  that make foreign keys and concurrent reads behave, the job queue, the DB-backed LLM
  cache, the repository, and an Alembic migration that round-trips on SQLite.
- `worker/`: the polling loop, `run_pipeline` / `recheck` / `purge`, retries with
  backoff, and stale-claim recovery so a killed worker's job is picked up by another.
- `api/`: the full `/api/v1` surface, upload validation, the single auth seam, and audit
  writes.
- `user-ui/`: Next.js 15 with all five Phase 3 screens, the ui2 theme, the `/api/*`
  rewrite proxy, a standalone Dockerfile, and 35 Vitest tests.
- 602 Python tests and 35 frontend tests; every gate clean.

### Notable decisions and fixes

- `get_data_dir` read the environment instead of application state, so an injected data
  directory was silently ignored. Found by a test that asserted the files actually
  landed on the volume.
- A live run against an empty database exposed a real defect: with no alias configured,
  stage 5 reported "Config has no condition on score" because the config calls it
  `SCORE_V3`. Stage 4 had already decided the element implements the requirement, so
  stage 5 now pairs a single condition on each side when the alias table has never heard
  of the attribute. The guard is narrow: a *known* attribute with no counterpart is
  still a real gap.
- A run awaiting a retry stays `queued` rather than flashing `failed` in the UI; only a
  dead job marks the run failed.
- The Runs list stops polling when nothing is queued or running.

### Pending

Phase 4, then Phase 5.

### Blockers

None. The compose run needs a machine with Docker.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phases 4 and 5 — admin-ui and the final report)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phases:** 4 and 5 · **Status:** both
complete, with two criteria unverifiable on this machine.

### Phase 4 — admin-ui and configurable checks

- The admin backend: report templates, named values with live resolution against the
  uploaded samples, versioned checks, compliance rules, reverse-pass categories,
  aliases, masked columns, and a usage dashboard that is plain SQL over the run tables.
- `POST /admin/checks/draft` is the only model call in the admin flow and happens once
  per check; testing a check never calls it.
- `admin-ui` on :3001, same toolchain and theme as user-ui, with all five screens.
- Added `validate()` to the expression evaluator. `referenced_names` only parsed, so
  `__import__('os')` could be *saved* and would have failed only at evaluation time.
  Saving now walks the same node rules the evaluator uses.

### Phase 5 — the frozen report

- A self-contained one-page HTML report: inline CSS, no network, opens from `file://`.
  Rendered once, hashed, stored, and never regenerated; a second finalize is a 409 and
  re-reviewing a finalized run is refused, so the file always matches the decisions it
  came from.
- The PDF is rendered from the **stored file**, behind a Protocol so the api depends on
  the capability rather than on Playwright. Playwright is the optional `[pdf]` extra,
  installed in the worker image; without it the endpoint returns 503 naming the HTML
  report rather than failing the download silently.
- The user-ui final report screen shows the stored page in an iframe rather than
  re-implementing it, so there is only ever one version of the document.

### Notable decisions

- Guards worth keeping: a named value a check still uses cannot be deleted; saving one
  reverse-pass category seeds the rest, so switching one off cannot silently enable the
  others; adding a masked column keeps the shipped defaults (ADR-003).
- Judgment checks have a prompt and a schema, and the UI flags them "use sparingly",
  but the worker still skips them: an expression check costs nothing and a judgment
  check costs a call per run, so wiring it in waits for a real need. Noted in
  `phase-4.md`.
- The report template uses `StrictUndefined`. A silently blank field in a frozen report
  is a defect nobody can fix afterwards, so a missing value fails at render time.

### Pending

Phase 6, and the user items under "Resume here".

### Blockers

None for Phase 6, though most of it wants the real file samples.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 6 — hardening, and the demo)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6 · **Status:** in progress —
everything doable from a development checkout is done.

### What was completed

- **ADR-018, the PII tripwire.** Every assembled prompt is scanned inside the adapter,
  before the cache and therefore before any path to the network, and a match **raises**
  rather than warns. The patterns match formats, not meanings, and a test asserts that
  ten samples of real pipeline text pass: a tripwire that fires on ordinary content
  gets switched off, which is worse than not having one. Matches are reported by
  pattern name and a redacted shape, never the value.
- Retention: the worker schedules its own 24-hour sweep, so no cron entry is needed,
  and `scripts/purge.py --dry-run` reports what would go before anything does.
- Audit completeness and log safety, both asserted by tests rather than reviewed by eye.
- `scripts/load_test.py`, and `scripts/seed_demo.py` which loads admin reference data
  plus eight runs covering every lifecycle state.
- The deployment checklist in `deployment.md`, with the in-house items marked as such.
- 731 Python tests, 35 user-ui, 10 admin-ui. Every gate clean.

### What the load test found

A real race, which is what a load test is for. Two workers on different runs reach the
same cache key — the key is a content hash, so an identical OSL section in two runs
produces one — both miss, both call the model, and both insert. The loser got a unique
constraint violation and **its run failed**. Three of twelve runs died under four
workers.

A cache write is an optimisation. Failing a run over one trades a saved call for a lost
run, which is the wrong way round. `DbCache.put` now treats a duplicate as what it is —
another worker stored the same answer for the same content — and any other write error
as a warning. Twelve of twelve now pass, and `tests/db/test_concurrency.py` covers it.
This would have happened on Postgres too.

### What the demo found

Bringing the UI up against real data showed three things the tests could not:

- Finished runs rendered an empty grey progress bar, because the list endpoint does not
  carry per-stage records. They now report their outcome instead.
- The failed run read "Failed at s1_parse: PipelineError: s1_parse: …" — the stored
  error already names its stage.
- With one day of history the usage sparkline filled the card edge to edge and read as
  a rendering fault. It now caps the bar width until there are enough points.

### Pending

The Phase 6 items that need real files, the in-house model, or the platform and
compliance teams. They are marked **in-house** in `phase-6.md` and listed under
"Resume here".

### Blockers

None that are mine. Everything left is on the user's list.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 7 — documented, dormant)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 7 · **Status:** documented only, as
asked. No code was written and nothing was started.

### What was completed

- `docs/phase-7.md`, "Real-world fit": the phase that runs on the machine holding the
  real OSL, config, and reports, and only when the user asks for it.
- ADR-019 recording why it is a separate phase rather than part of Phase 6: it happens
  on a different machine, at an unknown time, driven by files that cannot come here,
  and it is conversational rather than planned. Folding it into Phase 6 left a phase
  that could never be completed.
- Both phase tables, `CLAUDE.md`, and the README index updated. `CLAUDE.md` says
  plainly that a session must not act on Phase 7 because it noticed it exists.

### What is in the doc

- **The one rule** first, before anything else: a real customer file, or anything
  derived from one, never enters the repository. A table of what may come back out
  (shapes, counts, patterns, synthetic fixtures modelled on a shape) against what may
  not (any value, any row, any identifier), and an instruction to keep the real files
  outside the working tree.
- **How to invoke it** and the loop Claude runs each time: read the file with the
  existing parser, name the gaps specifically, say what changes and where and why,
  say what does *not* change, propose the fixture, then stop and wait.
- **Per-artifact assumption tables** — for the OSL, the config, and the reports — each
  row naming what the parser believes today and what would break it. These are derived
  from the code, which is what makes the analysis start from what the tool actually
  does. They go stale when a parser changes, and the ADR says who updates them.
- **Where changes will land**, with a note that a change reaching `pipeline/` or
  `rules/schema.py` is a signal that a design assumption was wrong, not a parsing detail.
- Bootstrap steps for the new machine, including taking a golden-set baseline *before*
  touching prompts, so a later accuracy drop is visible.

### Pending

Nothing. The phase is dormant until the user asks for it.

### Blockers

None.

### Next concrete action

See "Resume here". Phase 7 is not it.

## Session: 2026-09-18 (PDF download fix)

**Branch:** `claude/funny-cerf-jsyvpe` · **Status:** fixed and verified with a real
browser. Phase 5 is now complete on every criterion.

### The report

Clicking "Download PDF" saved a JSON file.

### What was actually wrong — three things

1. **Playwright was not installed**, so the endpoint correctly answered 503 with a JSON
   body explaining that. Installed it and Chromium; PDFs now render.
2. **The UI could not tell.** It used a plain `<a href download>`, which has no way to
   check a status: it saved the 503 body under the name the user expected. It now
   fetches through the API client, which raises on a non-2xx and on a 200 that is not a
   PDF, and only a real document reaches the disk. The run detail carries
   `pdf_available`, so the button is disabled with an explanation rather than failing
   after the click.
3. **The PDF was missing its content**, which only showed up once one could be made:
   one page, 1021 characters, every section a heading with nothing under it. The print
   rule `details .body { display: block }` cannot work, because a closed `<details>`
   hides its children through the browser's own mechanism rather than through a style.
   The report now sets `open` on every section before printing, and the renderer does
   the same itself so an already-frozen report still prints in full. Two pages, 3147
   characters, all seven matrix rows, every reviewer comment.

Two smaller things the verification caught: the disclosure arrow printed, because
`details[open] summary::before` outranked the rule meant to hide it; and identifiers
wrapped mid-token, so `R-001` arrived in the PDF as `R-` and `001`.

### A note worth keeping

Run 9 had already cached a PDF from the broken renderer. The HTML is the frozen record
and must never be regenerated (ADR-005), but the **PDF is a rendering of it** —
re-rendering the same HTML gives the same document. So after fixing a renderer, delete
`data/reports/*.pdf` and they rebuild. That is now a line in the deployment checklist
and a comment at the point in the code where the decision is made.

Run 9 also demonstrated the freeze working as intended: its stored HTML predates the
template fix and still carries the old stylesheet, while its PDF now prints in full
because the *renderer* opens the sections. That is why the fix went in both places.

### Tests

Four regression tests on the API side and four in the UI client, covering the exact
shape of the bug: a 503 must be an unmistakable status with a non-PDF body, a 200 must
be a real PDF with a filename, and the client must raise rather than hand back bytes in
either failure case. 732 Python tests, 39 user-ui, 10 admin-ui.

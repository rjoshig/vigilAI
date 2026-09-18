# Session Log

Working journal. **Read the "Resume here" block first at the start of every session; update
it and append an entry at the end.** Required fields per entry: branch, phase, status,
what was completed, what's pending, blockers, next concrete action. No PII, no customer
names, no sample data.

---

## Resume here

| Field | Value |
| --- | --- |
| Current phase | **2 — Pipeline core (CLI)** |
| Current milestone | 2a–2c done (fixtures, parsers, rules, LLM adapter); **2d next** (stages 1–5) |
| Branch | `claude/funny-cerf-jsyvpe` (Phase 0 PR still open against `main`) |
| Last updated | 2026-09-18 |

**Next action:** milestone 2d — `pipeline/s1_parse.py` … `s5_compare.py` and
`pipeline/run.py` (orchestrator with per-stage status and resume from the last good
stage). Stage 4 shortlists by `req_type` + alias in code, links exact matches without a
call, and asks the judge only about unclear pairs. The acceptance test is the design
doc's worked example (IL/AZ vs IL/AZ/TX) end to end on the mock client; the
`geography_extra_state` fixture case already encodes it.

**Environment:** `.venv` on Python 3.10.14; `source .venv/bin/activate` then
`black . --target-version py310 && flake8 && mypy src/ && pytest`. Fixtures regenerate
with `python scripts/generate_fixtures.py --out tests/fixtures` (the suite generates its
own into a temp directory, so committed fixtures are not required).

**Blocked on the user (does not block 2d–2f):** a sanitized shape reference for the real
OSL / config / report layouts, and a local model for the 2f benchmark (deferred by
ADR-014). Remaining open questions are in `docs/phase-plan.md`.

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

- Studied `compare-file` (layout, CLAUDE.md, `standards/`, `docs/` phase + ADR + session
  log conventions, `ui-mock/`, `ui2` toolchain, pyproject) and `snopfamily` (CLAUDE.md
  router style, `AI_CONTEXT/` set, GIT_RULES, PR template, CI).
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

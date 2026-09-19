# Phase 2 — Pipeline core (CLI)

**Status:** ✅ **complete** (2026-09-18), with one criterion deliberately open:
milestones 2a–2f are done and acceptance criteria 1 and 3–5 are met, but criterion 2's
real-model benchmark is deferred by ADR-014 until a model is available. Phase 3 may
start; this must close before Phase 6.

**Goal:** the whole nine-stage pipeline runnable from the command line on synthetic
fixtures: files in, findings JSON out. Parsers, the canonical rule schema, the LLM
adapter with cache, and a golden set that measures extraction accuracy.
Effort 4–5 weeks. This is the riskiest phase (LLM extraction quality), which is why it
comes before the web app.

Read `design.md` "Processing pipeline", "Canonical rule schema", "Findings", "LLM
adapter", "LLM cost controls", and `llm-privacy.md` end to end before starting.

## Milestones (sequential; each ends with tests green and a session-log entry) · 🟡 in progress

### 2a — Fixtures and parsers behind Protocols · ✅ complete
- [x] `scripts/generate_fixtures.py`: from a small spec, emit a **synthetic** OSL `.docx`
      (headings + criteria tables), a config `.json` (blocks with filters, attributes,
      waterfall steps), and report `.xlsx` files (DIRT with a masked-able sample tab,
      field / state / score distributions, counts, cross tabs). Seeded RNG.
- [x] `parsers/base.py`: `OslParser`, `ConfigParser`, `ReportParser` Protocols and the
      parsed-document dataclasses (`OslSection`, `OslTable`, `ConfigBlock` with JSON path,
      `ReportSheet` with cell addresses).
- [x] `parsers/osl_docx.py` (python-docx by heading and table), `parsers/config_json.py`
      (split into logical blocks), `parsers/reports/*.py` (one per report type; openpyxl
      read-only).
- [x] Masking of the DIRT sample tab from a masked-column list (default: obvious PII
      names) at parse time.
- [x] Tests: one file per parser; round-trip against the generated fixtures. 73 tests,
      97% branch coverage. A PII regex tripwire asserts no parsed value looks like a real
      identifier.

### 2b — Canonical rule schema and normalizers · ✅ complete
- [x] `rules/schema.py`: Pydantic models for the rule envelope (`req_type`, conditions,
      operators, actions, `source_ref`/`source_text`, confidence), findings, traces.
- [x] `rules/normalize.py`: state names → codes, ranges → intervals, lists → sets,
      attribute names → canonical via aliases.
- [x] `rules/derive.py`: derived report checks per operator.
- [x] Tests: every operator; every `req_type` example from the design doc. 165 tests
      total, 98% branch coverage.

### 2c — LLM adapter, cache, prompts · ✅ complete
- [x] `llm/client.py`: `LLMClient` Protocol, `LLMResult`, `LLMError`.
- [x] `llm/openai_compat.py` (`/chat/completions`), `llm/anthropic.py` (`/v1/messages`),
      `llm/mock.py` (canned JSON by prompt version), `llm/factory.py` from `.env`.
- [x] `llm/cache.py`: key = sha256(content) + model + prompt version; **checked before
      every call**. Phase 2 backend: SQLite file or JSON on disk behind a small interface;
      Postgres in Phase 3 (same interface).
- [x] `llm/calls.py`: one record per call (tokens, latency, retries, ok); per-run token
      budget with a hard stop. Landed as `CallRecord` / `CallLog` in `llm/client.py` and
      the budget check in `llm/base.py`, so every provider inherits both.
- [x] `llm/prompts/`: stage 2, 3, 4, 8, 9 templates, each with a `VERSION` and 2–3 worked
      examples; JSON-only output validated by schema; one retry with the error appended.
- [x] Tests: cache hit/miss, budget stop, provider request shapes via `httpx` mock
      transport, no network. 282 tests total, 97% branch coverage. An autouse fixture
      blocks the socket layer for the whole suite, so no path to the network can be
      added by mistake in a later phase.

### 2d — Stages 1–5 · ✅ complete
- [x] `pipeline/s1_parse.py` … `s5_compare.py`, `pipeline/run.py` orchestrator with
      per-stage status, resume from the last good stage.
- [x] Stage 4 shortlists by `req_type` + alias in code, links exact matches without the
      LLM, and asks the judge one narrow question per unclear pair.
- [x] Tests: the worked example from the design doc (IL/AZ vs IL/AZ/TX) end to end with
      the mock client, plus a direct test per comparison branch. 341 tests total, 94%
      branch coverage.

### 2e — Stages 6–9 · ✅ complete
- [x] `pipeline/s6_reverse.py` (scoped categories), `s7_reports.py` (per-`req_type`
      checks + the expression evaluator in `checks/`), `s8_verify.py`, `s9_summarize.py`.
- [x] `checks/expressions.py`: safe evaluator over named values (no `eval`), "could not
      evaluate" findings.
- [x] Tests: every finding type in the design doc table is produced by at least one
      fixture. 475 tests total, 94% branch coverage. The evaluator has an escape-attempt
      suite (imports, dunder access, comprehensions, exponentiation).

### 2f — CLI and golden set · 🟡 in progress
- [x] `cli.py`: `greenlight-ai run --osl … --config … --report dirt=… --report counts=… --out
      findings.json`, `--provider mock|openai|anthropic`, `--log-level`.
- [x] The golden set: 12 synthetic cases with known-correct rules, generated by
      `scripts/generate_fixtures.py` with each case's oracle in `manifest.json`;
      `scripts/golden_set.py` prints precision and recall per finding type.
      `scripts/synthetic_model.py` holds the scripted stand-in that answers the LLM
      stages by reading the prompt, so the harness needs no model.
- [ ] Run the golden set against a local Gemma via Ollama and record the numbers in
      `docs/benchmarks/phase-2.md`. **Deferred by ADR-014**; the harness is
      provider-agnostic, so this is one command with no code change.

## Acceptance criteria · 🟡 in progress

1. [x] `greenlight-ai run …` on the fixtures produces a findings JSON matching an oracle
   file. The oracle travels with each fixture in `manifest.json`.
2. [~] The golden set runs without a model in CI (12 / 12 cases, recorded in
   `docs/benchmarks/phase-2-synthetic.md`) and 12 / 12 on a first real model
   (`docs/benchmarks/phase-2-real-model.md`, ADR-028). The run against the in-house
   gateway on real files is **deferred** to the target environment (ADR-028).
3. [x] No prompt contains a sample row. Masking happens at parse time, a PII regex
   tripwire covers the parsers and the prompts, and an autouse fixture blocks the
   socket layer for the whole suite.
4. [x] Cache: a second identical run makes zero network calls (asserted).
5. [x] `black`, `flake8`, `mypy --strict`, `pytest` clean. 505 tests, 95% branch
   coverage.

## Out of scope

Postgres, the queue, the API, any UI, PDF.

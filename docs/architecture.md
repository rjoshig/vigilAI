# Architecture

The product design is [`design.md`](design.md); this page says how the code is organised
to deliver it. Keep the two in sync: a change here that alters behaviour needs an ADR in
[`decisions.md`](decisions.md).

## High-level shape

```
 Associate browser ──▶ user-ui (Next.js :3000) ──┐
                                                 ├──▶ api (FastAPI :8000) ──▶ postgres (data + queue)
 Admin browser ─────▶ admin-ui (Next.js :3001) ──┘          │                     ▲
                                                            ▼                     │
                                                    shared volume  ◀──── worker (Python) ──▶ in-house LLM
                                                    (uploads, reports, PDFs)      (via the one adapter)
```

- **api** only accepts requests, validates uploads, writes rows, and enqueues a job. It
  never parses a file or calls the LLM.
- **worker** claims jobs from the `jobs` table and runs the pipeline. Scale with
  `docker compose up --scale worker=N`.
- **the database** holds every table in `design.md` "Data model", plus the `jobs` queue
  and the LLM cache. `DATABASE_URL` selects **SQLite** (the default, and all a laptop
  needs) or **Postgres** (what compose configures, because SQLite takes one writer at a
  time) — ADR-017. The filesystem holds only files; the DB holds their paths and hashes.
- **shared volume** is mounted into api and worker. Single host by design; NFS or an
  object store only if workers ever move hosts (ADR-007).
- Both UIs proxy `/api/*` to the api so the browser never meets CORS. Progress is polled
  every 3 s; no WebSockets.

## The Python package — `src/vigilai/`

One installable package; api and worker are two entry points over the same code.

| Subpackage | Responsibility |
| --- | --- |
| `parsers/` | **Protocols** `OslParser`, `ConfigParser`, `ReportParser` + one implementation each (ADR-006). OSL: python-docx by heading and table. Config: JSON split into logical blocks with their JSON paths. Reports: one fixed parser per report type (DIRT, field distribution, state distribution, counts, score distribution, cross tabs) via openpyxl/pandas. Sample-row **masking** happens here, at parse time, from the admin-maintained masked-column list. |
| `rules/` | The **canonical rule schema** (Pydantic): `req_type` ∈ criteria · geography · value_set · attributes · waterfall · quantity · other, with conditions, operators, actions, `source_ref`/`source_text`, confidence. Normalizers (state names → codes, ranges → intervals, lists → sets). **Derived checks** per operator (`age < 21 → reject` ⇒ `accepts.age.min >= 21`) — fixed code, never LLM output. |
| `llm/` | The **single adapter** (ADR-004): `LLMClient` Protocol, `OpenAIClient` (`/chat/completions`, covers vLLM/TGI/Ollama/gateways), `AnthropicClient` (`/v1/messages`), `MockClient` (canned JSON for tests). Plain `httpx`, no SDKs. Factory from `LLM_PROVIDER`. The **cache** (`llm_cache`, key = sha256(content) + model + prompt version) is checked before every call (ADR-005); every call writes an `llm_calls` row; a per-run token budget stops a runaway run. Prompt templates live here with a version constant each. JSON-only output validated against a Pydantic schema; on failure retry once with the validation error appended. |
| `pipeline/` | One module per stage, an orchestrator, and resume logic. Each stage records status/duration/tokens in `run_stages` and is idempotent: a retried job resumes at the last good stage. |
| `checks/` | Report checks per `req_type` (geography ⇒ state-distribution keys ⊆ allowed set; criteria ⇒ DIRT min/max respect the interval; attributes ⇒ fields exist; waterfall ⇒ counts reconcile per step; quantity ⇒ counts report). The **expression evaluator** for admin-defined checks over named values (safe, no `eval`), compliance-rule presence, and the reverse-pass category scoping. A value that cannot be resolved becomes a "could not evaluate" finding, never a silent skip. |
| `db/` | SQLAlchemy 2 models for every table in `design.md` "Data model" (`users` included but unused, ADR-008), Alembic migrations (additive only, portable across both backends), session helpers, the `jobs` queue, the DB-backed LLM cache, the repository that converts between rows and pipeline objects, and the retention purge. |
| `api/` | FastAPI app under `/api/v1`: runs (create with fingerprint check + `rerun_reason`, list, get, requirements, recheck, findings, finalize, report, report.pdf, clone, stats), configs, admin (templates, named values, checks + draft + test, compliance rules, aliases, usage). Pydantic wire models. **One auth dependency** every router uses, a no-op in v1 (ADR-008). Upload validation: `.docx`/`.json`/`.xlsx` only, size limit, content-type check, macros ignored. Audit log writes. |
| `worker/` | The polling loop, the `run_pipeline` / `recheck` / `purge` tasks with backoff (3 retries, then the run is `failed` with the error shown in the UI), stale-claim recovery so a killed worker's job is picked up, and the retention purge. |
| `report/` | `render.py` builds the **one-page self-contained HTML report** from a Jinja2 template and returns it with its sha256; `finalize` stores it and marks the run `finalized` (frozen — never regenerated, ADR-005). `pdf.py` renders the **stored file** with headless Chromium behind a Protocol, so the api depends on the capability rather than on Playwright and a test can inject a fake. Playwright is the optional `[pdf]` extra, installed in the worker image. |
| `cli.py` | `vigilai run --osl … --config … --report kind=path …` → findings JSON. The first entry point (Phase 2) and the tool for the golden set. |

Dependencies point down: `api → db, worker(enqueue)`; `worker → pipeline, db`;
`pipeline → parsers, rules, llm, checks`; `checks → rules`; `llm → db`. `api` never
imports `pipeline`.

## The pipeline (design.md "Processing pipeline")

| Stage | Who | Module | Notes |
| --- | --- | --- | --- |
| 1 Parse files | code | `pipeline/s1_parse.py` | via the parser Protocols; masking applied |
| 2 Extract OSL requirements | LLM, cached | `pipeline/s2_extract.py` | one call per OSL section or table; output = canonical rules with confidence |
| 3 Describe config elements | LLM, cached | `pipeline/s3_describe.py` | one call per config block; same vocabulary; `is_technical` flag |
| 4 Trace requirement → config | code first, then LLM judge | `pipeline/s4_trace.py` | code shortlists by `req_type` + field alias and links exact matches; the judge sees only unclear pairs; verdict ∈ implemented · partial · contradicts · not related |
| 5 Compare values | code | `pipeline/s5_compare.py` | sets, intervals + operators, attribute lists, waterfall order |
| 6 Scoped reverse pass | code | `pipeline/s6_reverse.py` | only filters/select criteria, model data, compliance rules — category list from admin-ui |
| 7 Check reports + admin checks | code | `pipeline/s7_reports.py` | per-`req_type` checks + expression checks over named values |
| 8 Verify high-severity findings | LLM | `pipeline/s8_verify.py` | second opinion with evidence; disagreement ⇒ downgrade to Review |
| 9 Summarize | LLM | `pipeline/s9_summarize.py` | findings list only |

**Re-check** (user edited a rule or a trace link): stages 5–7 only, no LLM. **Review**
(OK / Not OK, comments) and **report download**: no LLM.

## Data flow per run

1. `POST /api/v1/runs` validates each upload (extension, content type, size), stores the
   files on the volume, computes the **input fingerprint** (hash of all inputs + active
   check versions), and either returns the existing run or, with a `rerun_reason`,
   creates a new `runs` row (`queued`) and enqueues the job. A per-order-number cap
   refuses a fourth queued run for the same order.
2. The worker claims the job, sets `running`, and runs stages 1–9, writing `rules`,
   `config_elements`, `traces`, `findings`, `run_stages`, `llm_calls`, `llm_cache`.
3. Status becomes `needs_review`. The user reviews findings and may edit rules/traces
   (`rules.version` increments; `findings.rules_version` records provenance) and re-check.
4. `POST /runs/{id}/finalize` renders the frozen report once (`final_reports`), status
   `finalized`. PDF is rendered from the stored HTML.
5. The nightly purge deletes runs past `expires_at` (created + 90 days) with their files,
   rules, findings, and stats; aggregated usage stats are kept.

## Pluggability seams (bake in from Phase 2)

1. **Parser Protocols** — real layouts arrive in-house last; swap implementations, not
   call sites.
2. **`LLMClient` Protocol + factory** — provider and model are `.env` only.
3. **Prompt version constants** — part of cache keys, so prompt tuning never serves stale
   results.
4. **Check definitions as data** — admin-defined named values + expressions, versioned;
   the evaluator is generic.
5. **The auth dependency** — one FastAPI dependency; login later touches no endpoint.
6. **Report renderer** — templates + a renderer function; the review screen and the final
   report draw on the same findings data.

## Privacy boundary

PII may exist only in the uploaded files on the volume and in masked form in the DB. It
never enters a prompt, a log line, a fixture, a commit, or a cache entry.
[`llm-privacy.md`](llm-privacy.md) is the full statement.

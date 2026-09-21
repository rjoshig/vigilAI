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

## The Python package — `src/greenlight_ai/`

One installable package; api and worker are two entry points over the same code.

| Subpackage | Responsibility |
| --- | --- |
| `parsers/` | **Protocols** `OslParser`, `ConfigParser`, `ReportParser` + one implementation each (ADR-006). OSL: python-docx by heading and table. Config: JSON split into logical blocks with their JSON paths. Reports: one fixed parser per built-in report type (DIRT, field distribution, state distribution, counts, score distribution, cross tabs) via openpyxl/pandas, plus a generic parser for the types an administrator defines (ADR-020). Sample-row **masking** happens here, at parse time, from the admin-maintained masked-column list. `record_layout.py` is the fourth artifact and the only optional one (ADR-060): the delivered file's own schema, one row per field with its name, data type and size, behind a `RecordLayoutParser` Protocol like the others. It resolves **its own** headings through the ladder, so a layout headed `Column Name` / `Type` / `Length` is the same document as one headed `Field name` / `Data type` / `Size`. `NON_REPORT_KINDS` in `base.py` is the one place saying which uploaded kinds are not report workbooks; the worker, the replay and the credit-date pre-flight read it. |
| `rules/` | The **canonical rule schema** (Pydantic): `req_type` ∈ criteria · geography · value_set · attributes · waterfall · quantity · other, with conditions, operators, actions, `source_ref`/`source_text`, confidence. Normalizers (state names → codes, ranges → intervals, lists → sets). **Derived checks** per operator (`age < 21 → reject` ⇒ `accepts.age.min >= 21`) — fixed code, never LLM output. `product_codes.py` is the catalogue an OSL can name instead of listing attributes (ADR-061): a pure value object the repository builds, expanding a code into the attributes it stands for **in code**, never by the model, and reporting a code nobody defined rather than expanding it to nothing. `describe.py` renders a rule as one line for a prompt, a finding or the requirements screen; it sits here rather than in `s4_trace` so the API can read it without importing a stage (ADR-071). |
| `llm/` | The **single adapter** (ADR-004): `LLMClient` Protocol, `OpenAIClient` (`/chat/completions`, covers vLLM/TGI/Ollama/gateways), `AnthropicClient` (`/v1/messages`), `MockClient` (canned JSON for tests). Plain `httpx`, no SDKs. Factory from `LLM_PROVIDER`. The **cache** (`llm_cache`, key = sha256(content) + model + prompt version) is checked before every call (ADR-005); every call writes an `llm_calls` row; a per-run token budget stops a runaway run. Prompt templates live here with a version constant each, each with its own worked examples; `examples.py` holds the administrator's library, which is validated against the stage's schema, scoped, capped at four and inserted into the *rendered* prompt after the built-in examples (ADR-038). JSON-only output validated against a Pydantic schema; on failure retry once with the validation error appended. |
| `pipeline/` | One module per stage, an orchestrator, and resume logic. Each stage records status/duration/tokens in `run_stages` and is idempotent: a retried job resumes at the last good stage. |
| `resolve/` | **Which sheet, column, label or attribute did they mean** (ADR-054, ADR-062). One **ladder**, tried in order and stopping at the first unambiguous answer: exact, separators-as-noise, the same words, an alternate somebody wrote down, and — only where all four failed — the model, shown names and never values, its answer checked against the list it was offered. **A rung that ties is a rung that failed**, at every rung including the model's. `ladder.py` and `normalize.py` are leaves importing nothing; `attributes.py` answers *does this artifact carry this attribute* for all three callers and tells **missing** from **could not tell** by evidence (ADR-059); `dictionary.py` is rung 4's data for attribute names, built from `attribute_terms`/`attribute_spellings`; `layout.py` holds the per-run bookkeeping — one model call per distinct name, what the model reached (offered back to a person), and the **soft** cap on attribute lookups, past which the run stops asking and says what it did not look for. It takes names and returns names, which is what keeps it below `parsers/` and `checks/` rather than beside them. |
| `scopes.py` | **Where a definition applies**, and the only module that interprets a scope string (ADR-037). A `Scope` value object with `parse` (every form ever stored), `token` (the canonical one: `everywhere`, `programme:CODE`, `customer:NAME`, `config:ID`), `covers` and `label`. The stored columns are never rewritten; a row becomes canonical when somebody next saves it. `admin-ui/components/scope-picker.tsx` is the console's half of the same vocabulary. |
| `config/` | The three-layer settings resolution (ADR-023): a registry declaring every setting, a store resolving console over `.env` over default, and envelope encryption for the one secret an administrator can set. Nothing is read at import time. |
| `auth/` | Accounts, scrypt passwords, and server-side sessions (ADR-022). Login ships off; there is always a current user, the seeded placeholder when it is. **`roles.py` is the capability matrix** (ADR-049): three roles — `user`, `reviewer`, `admin` — each granting a set of capabilities, and a person holds several so what they may do is the union. It is a leaf: pure, typed, importing nothing else in the package, because it is the one place that answers *who may do what*. An account stores its roles as a JSON list and nothing else; membership is tested in Python, never in SQL, because JSON containment is spelled differently on SQLite and Postgres (ADR-017). |
| `training/` | The learning loop (ADR-021): the rule lifecycle `draft → shadow → active ⇄ disabled → deleted`, and synthesis turning reviewers' sentences into candidate rules that a person approves. Approval writes into the existing rule tables, so there is one evaluator. `front_door.py` is one step in front of it (ADR-037): the model says which existing surface an administrator's sentence belongs on, and synthesis does the rest unchanged. Background is offered rather than forced into a rule; an unplaceable sentence creates nothing. **`demotion.py` and `signatures.py`** are the second half (ADR-043): they group findings into signatures — one customer, one programme, one rule, one thing it fired on — count the verdicts people gave each, and decide which have earned their way out of the review queue. The decision is arithmetic over human verdicts; the model is not consulted and its confidence is not evidence. In Phase 6.18a it is **recorded and acted on by nobody**, so every reviewer still sees every finding. |
| `meaning/` | What a requirement answers to (Phase 6.10, ADR-033): samples in scope, the mapping interview (one cached model call per OSL section proposing requirement → config block → report cells), the compiler turning a confirmed entry into named values and a shadow check or a shadow compliance rule, and the run-time renderer that layers global entries under a programme's. |
| `coverage/` (in `pipeline/`) | `pipeline/coverage.py`: one state per requirement — checked · traced_unchecked · untraced · manual — and how many checks touched each report, from the tally stage 7 keeps. Pure code. `api/gate.py` turns it into the finalize gate and the attestation the reviewer confirms (ADR-035). |
| `checks/` | Report checks per `req_type` (geography ⇒ state-distribution keys ⊆ allowed set; criteria ⇒ DIRT min/max respect the interval; attributes ⇒ fields exist; waterfall ⇒ counts reconcile per step; quantity ⇒ counts report). The **expression evaluator** for admin-defined checks over named values (safe, no `eval`), compliance-rule presence, and the reverse-pass category scoping. A value that cannot be resolved becomes a "could not evaluate" finding, never a silent skip. **Matching that survives being spelled differently** lives here too: `compliance_match.py` (four path tests, Phase 6.15) and `programme_match.py` (three word tests plus the rule that a programme is named only on words it alone claims, Phase 6.17a). The `attributes` check reads the DIRT **and** the record layout and answers **once** between them, because an attribute the order asked for and neither artifact carries is one problem and not two (Phase 6.22e); `attribute_suggestions.py` proposes what a delivery calls the ones it could not locate, read out of the record layout in code at no model call where that settles it, and from the fifth rung where it does not. |
| `db/` | SQLAlchemy 2 models for every table in `design.md` "Data model" (`users` included but unused, ADR-008), Alembic migrations (additive only, portable across both backends), session helpers, the `jobs` queue, the DB-backed LLM cache, the repository that converts between rows and pipeline objects, the retention purge, and `replay.py`, which re-parses recent finalized runs' stored reports and runs a drafted rule over them with the pipeline's own evaluators, no model involved (Phase 6.13e). |
| `api/` | FastAPI app under `/api/v1`: runs (create with fingerprint check + `rerun_reason`, list, get, requirements, recheck, findings, finalize, report, report.pdf, clone, stats), configs, admin (artifact types and their AI context, delivery programmes, named values, checks + draft + test, compliance rules, aliases, usage, versions with revert, bulk deletes under the typed word, meaning, coverage and acknowledgements, the samples a reviewer explores, the public appearance). Pydantic wire models. Every delete requires `?confirm=delete` (ADR-032). **One auth dependency** every router uses (ADR-008), and on top of it **one guard per capability**: `deps.require_capability(Capability.X)` builds a dependency that refuses 403 (never 404) with the act named, and a route asks for the act it performs rather than for a role. The two routes serving several resources — the bulk delete and a definition revert — call `assert_capability` once the path parameter says which one applies. `GET /auth/me` returns the resolved capabilities so neither console reimplements the matrix. Upload validation: `.docx`/`.pdf`/`.json`/`.xlsx` only, size limit, content-type check, macros ignored. Audit log writes. |
| `chat/` | The report chat (Phase 8): `pack.py` assembles everything the chat may see about one frozen run and hashes it, `answer.py` runs one turn and checks its citations, `settings.py` resolves the nine console switches. Imported by `api/` and importing nothing above `db/`, `llm/` and `textfit` — which is why the shared prompt-fitting helpers moved down into `textfit.py` rather than being copied, since `api/` may never import a `pipeline/` stage and `fit`/`clip` are needed by both sides (ADR-071). |
| `worker/` | The polling loop, the `run_pipeline` / `recheck` / `purge` / `replay` tasks with backoff (3 retries, then the run is `failed` with the error shown in the UI), stale-claim recovery so a killed worker's job is picked up, and the retention purge. |
| `report/` | `render.py` builds the **one-page self-contained HTML report** from a Jinja2 template and returns it with its sha256; `finalize` stores it and marks the run `finalized` (frozen — never regenerated, ADR-005). `pdf.py` renders the **stored file** with headless Chromium behind a Protocol, so the api depends on the capability rather than on Playwright and a test can inject a fake. Playwright is the optional `[pdf]` extra, installed in the worker image. |
| `cli.py` | `greenlight-ai run --osl … --config … --report kind=path …` → findings JSON. The first entry point (Phase 2) and the tool for the golden set. |

Dependencies point down: `api → db, worker(enqueue)`; `worker → pipeline, db`;
`pipeline → parsers, rules, llm, checks`; `checks → rules, resolve`; `parsers → resolve`;
`llm → db`. **`api` may import a pure `pipeline` leaf — `context`, `coverage`,
`guidance` — and never a stage** (ADR-071); `tests/test_architecture.py` enforces
both halves. `resolve/` is the lowest of these and imports
nothing from the package except itself, which is why `checks.reports` passes a resolver
to `resolve.attributes.present` through a **Protocol** rather than importing
`resolve.layout` — that module reaches `llm/`, and importing it would put a model adapter
into every parser.

## The pipeline (design.md "Processing pipeline")

| Stage | Who | Module | Notes |
| --- | --- | --- | --- |
| 1 Parse files | code | `pipeline/s1_parse.py` | via the parser Protocols; masking applied |
| 2 Extract OSL requirements | LLM, cached | `pipeline/s2_extract.py` | one call per OSL section or table; output = canonical rules with confidence |
| 3 Describe config elements | LLM, cached | `pipeline/s3_describe.py` | one call per config block; same vocabulary; `is_technical` flag |
| 4 Trace requirement → config | code first, then LLM judge | `pipeline/s4_trace.py` | code shortlists by `req_type` + field alias and links exact matches; the judge sees only unclear pairs; verdict ∈ implemented · partial · contradicts · not related |
| 5 Compare values | code | `pipeline/s5_compare.py` | sets, intervals + operators, attribute lists, waterfall order |
| 6 Scoped reverse pass | code, then LLM only where code failed | `pipeline/s6_reverse.py` | only filters/select criteria, model data, compliance rules — category list from admin-ui. A compliance rule whose four deterministic path tests all miss puts one narrow question to the model — *where is this implemented, if anywhere* — and code checks the answer against the paths it offered, applies a confidence floor, and makes a located control a review item, never a pass (ADR-036 shape, Phase 6.15) |
| 7 Check reports + admin checks | code, then LLM only where code failed | `pipeline/s7_reports.py` | per-`req_type` checks + expression checks over named values; records what it evaluated, which `pipeline/coverage.py` turns into the run's coverage (ADR-035). The programme classification check matches keywords through `checks/programme_match.py`, tolerant of plurals, hyphens and reordered phrases; where none of the declared programme's words appear it asks the model once *which programme do these documents read like*, and code decides what the answer means — the model may soften a high-severity finding and never erase one (ADR-045) |
| 8 Verify high-severity findings | LLM | `pipeline/s8_verify.py` | one second opinion, or three independent lenses merged by code (ADR-034); disagreement ⇒ downgrade to Review with every reason; a lens's proposal and an unevidenced requirement that reads like an obligation each become a Review item |
| 9 Summarize | LLM | `pipeline/s9_summarize.py` | findings list only |

**Re-check** (user edited a rule or a trace link): stages 5–7 only, no LLM. It is
queued by the edit, never by a button, and it leaves the run in `needs_review` — so
`RunDetail.rechecking`, read from the job queue, is what says one is in flight and what
the Review screen polls on (Phase 6.23b). A re-check that fails leaves the run's status
alone: its findings are rebuilt from rows that are already stored, so the run is still
reviewable. **Review** (OK / Not OK, comments) and **report download**: no LLM.

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
4. **The catalog as data** — which artifacts the tool accepts, what each means, and
   which delivery programme a run belongs to are rows an administrator edits, not code
   (ADR-020). `parsers/osl.py` picks the OSL parser by suffix: `osl_docx.py` for Word,
   `osl_pdf.py` for PDF (text cut into numbered sections; a scanned PDF needs OCR
   first). `db/versions.py` snapshots every save of an artifact type or a
   programme's rule set, lists the last ten, reverts one as a new version, and
   prunes the rest on the retention sweep (ADR-029). `db/catalog.py` holds the shipped defaults and seeds them;
   `pipeline/guidance.py` turns what is configured into a prompt preamble and returns
   nothing when nothing is configured.
5. **Check definitions as data** — admin-defined named values + expressions, versioned;
   the evaluator is generic.
6. **The auth dependency** — one FastAPI dependency; login later touches no endpoint.
7. **Report renderer** — templates + a renderer function; the review screen and the final
   report draw on the same findings data.

## The in-product Guide

Each app carries a **Guide** screen whose content is generated, not written twice
(ADR-050). `scripts/build_guides.py` reads the sections that `docs/user-training.md` and
`docs/admin-training.md` mark for it — position and Guide title declared in the document
— and writes `lib/guide.generated.ts` in each app: already-parsed blocks with inline
emphasis resolved into spans, so `components/guide-view.tsx` draws them without
interpreting anything. Neither app carries a markdown renderer.

`scripts/check_docs.sh` and `tests/docs/test_guides.py` both run the generator with
`--check`, so a training document edited without a rebuild fails the gate a contributor
already runs. The generated files are in each app's `.prettierignore`: the generator
formats them, and prettier reformatting them would fail a comparison on a file nobody
edited. `ui.guide` offers or withdraws the Guide in both sidebars and gates nothing else.

## Browser tests

`e2e/` holds Playwright tests over both apps against a real API, a real worker and a
throwaway SQLite database seeded by `scripts/seed_demo.py`. They cover what a unit test
cannot: that a screen renders what the API returned, that a decision reaches the server,
and that the finalize gate refuses in a browser and not only in a test client. The
scripted stand-in answers every model call, so they need no network
([`e2e/README.md`](../e2e/README.md)).

A finding card carries `data-testid`, `data-severity`, `data-finding` and
`data-review-status` so a test can assert an outcome rather than a message that appears
and clears.

## Privacy boundary

PII may exist only in the uploaded files on the volume and in masked form in the DB. It
never enters a prompt, a log line, a fixture, a commit, or a cache entry.
[`llm-privacy.md`](llm-privacy.md) is the full statement.

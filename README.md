# Greenlight AI

Automated QC validation for a credit-data fulfillment process.

The tool reconciles three things that today are checked by eye: the requirement spec
(**OSL**, a Word document), the ETL configuration (JSON), and the output reports (Excel:
DIRT, field / state / score distributions, counts, cross tabs). It checks that every OSL
requirement made it into the config, and then into the results.

**The LLM reads, code checks.** The LLM extracts requirements, judges whether a config
element means the same thing as an OSL requirement, and writes the explanation. Every value
comparison (sets, ranges, counts, report numbers) is deterministic Python, so results are
exact, repeatable, and auditable. The **OSL is the source of truth**.

A user fills a short form, uploads the files, and submits. A worker runs the pipeline; the
user reviews the findings (OK / Not OK with comments) and generates a frozen one-page HTML
report with PDF download. Runs, configs, and stats are kept for 90 days.

Full design: [`docs/design.md`](docs/design.md). How to work here: [`CLAUDE.md`](CLAUDE.md).

## Status

**Phase 0 (repo setup) in progress.** No application code yet. Roadmap and status:
[`docs/phase-plan.md`](docs/phase-plan.md). Latest state and resume point:
[`docs/session-log.md`](docs/session-log.md).

## Architecture at a glance

Five containers in one `docker-compose.yml`, plus the in-house LLM endpoint. Postgres is
both the data store and the job queue; files sit on one shared Docker volume. No Redis, no
broker, no object store. No login in v1 (internal network only).

| Service | Folder | Tech | Job |
| --- | --- | --- | --- |
| user-ui | `user-ui/` | Next.js, TypeScript, Tailwind | New run, run history, review screen, report viewer, config history |
| admin-ui | `admin-ui/` | Next.js, same theme, own URL | Artifact types and their meaning, delivery programmes, check definitions, compliance rules, aliases, usage |
| api | `src/greenlight_ai/api/` | FastAPI, SQLAlchemy, Alembic, Pydantic | Uploads, run CRUD, enqueue, reviews, serve reports |
| worker | `src/greenlight_ai/worker/` + `pipeline/` | Python, Procrastinate, python-docx, openpyxl, pandas, Jinja2, Playwright | The nine-stage pipeline and PDF rendering |
| postgres | — | Postgres 16 | Metadata, rules, findings, checks, stats, LLM cache, job queue |

Details: [`docs/architecture.md`](docs/architecture.md).

## Repository layout

```
greenlight-ai/
├── CLAUDE.md              # how to work on this repo (read first)
├── README.md              # you are here
├── pyproject.toml         # package + black / mypy / pytest config
├── .flake8  .python-version  .editorconfig  .env.example  .gitignore
├── docker-compose.yml     # postgres, api, worker, user-ui, admin-ui
├── docker/                # api.Dockerfile, worker.Dockerfile
├── .github/               # PR template, manual-only CI workflow
├── standards/             # canonical coding standards: python, frontend, git
├── docs/                  # design doc, architecture, phase docs, ADRs, session log
├── scripts/               # developer tooling (docs check; fixture generator from Phase 2)
├── src/greenlight_ai/           # the Python package: api + worker + pipeline
├── tests/                 # pytest suite; synthetic fixtures only
├── mock/                  # static clickable mock: shared/, user-ui/, admin-ui/ (Phase 1)
├── user-ui/               # associate-facing Next.js app (Phase 3)
└── admin-ui/              # operator Next.js app, own URL (Phase 4)
```

## Setup (macOS, Apple Silicon)

Requires **Python 3.10** (floor and pin; 3.11 / 3.12 also work), Node 20+, Docker Desktop.

```bash
git clone https://github.com/rjoshig/vigilAI && cd vigilAI
pyenv install 3.10.14 && pyenv local 3.10.14
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # LLM_PROVIDER=mock by default; see docs/deployment.md
pytest                          # Phase 0: one package smoke test
```

Local LLM for development: Ollama's OpenAI-compatible endpoint with a Gemma model
(`LLM_PROVIDER=openai`, `LLM_BASE_URL=http://localhost:11434/v1`), or the Anthropic API
(`LLM_PROVIDER=anthropic`). The same code runs everywhere; only `.env` differs.

The web stack (from Phase 3): `docker compose up --build`, then user-ui on
http://localhost:3000 and admin-ui on http://localhost:3001.

## Documentation

- [`docs/design.md`](docs/design.md) — **the design doc; source of truth for the product**
- [`docs/architecture.md`](docs/architecture.md) — containers, package layout, pipeline stages, data flow
- [`docs/phase-plan.md`](docs/phase-plan.md) — phase-by-phase roadmap and status
- [`docs/phase-0.md`](docs/phase-0.md) … [`docs/phase-6.md`](docs/phase-6.md) — detailed per-phase plans
  ([phase-1](docs/phase-1.md), [phase-2](docs/phase-2.md), [phase-3](docs/phase-3.md),
  [phase-4](docs/phase-4.md), [phase-5](docs/phase-5.md))
- [`docs/phase-6.1.md`](docs/phase-6.1.md) — **richer inputs and a trainable rule loop**:
  several samples per artifact type, several files per report, workbook type detection,
  and Train AI mode (ADR-021)
- [`docs/phase-6.2.md`](docs/phase-6.2.md) — **optional login and attribution**: two
  `.env` switches, accounts an administrator creates, and who-did-what on every run,
  review, and suggestion (ADR-022)
- [`docs/phase-6.3.md`](docs/phase-6.3.md) — **runtime settings in the admin console**:
  the console overrides `.env`, which overrides the built-in defaults (ADR-023)
- [`docs/phase-6.4.md`](docs/phase-6.4.md) — **showing the mode, and notes that follow a
  configuration**: a Train AI indicator in both apps, and standing notes on a
  configuration id that reach the model and the admin queue
- [`docs/phase-6.5.md`](docs/phase-6.5.md) — **training documentation, kept current**: a
  recurring phase re-entered after every milestone
- [`docs/phase-6.6.md`](docs/phase-6.6.md) — **themes**: named themes, a picker that
  steps through them, and the default and lock set from the admin console (ADR-031)
- [`docs/user-training.md`](docs/user-training.md) — **user training**: the user app,
  screen by screen, for associates
- [`docs/admin-training.md`](docs/admin-training.md) — **administrator training**: the
  admin console, the training queue, the rules, and a weekly routine
- [`docs/presentation-brief.md`](docs/presentation-brief.md) — **design brief** for slide
  decks and management documents: the design, its reasons, the diagrams, and what it
  changes for an associate, at a general-audience level
- [`docs/gd-rollout-plan.md`](docs/gd-rollout-plan.md) — **Global Delivery rollout**:
  ownership, support tiers, escalation, change and release, acceptance criteria, the
  intake questionnaire, and the four gated stages from readiness to region by region
- [`docs/phase-6.7.md`](docs/phase-6.7.md) — **programme rules and the programme check**:
  several rules per programme with a strictness the model never grades, and a grep
  that confirms a run is the programme it says it is (ADR-026)
- [`docs/phase-6.8.md`](docs/phase-6.8.md) — **scoped compliance, validation guides, and
  versioned definitions**: checks and compliance scoped to a programme,
  a guide per report type that the model reads and code enforces, ten versions with revert (ADR-029)
- [`docs/phase-6.9.md`](docs/phase-6.9.md) — **delivery drift**: what changed since the
  previous finalized run of the same configuration, on the review screen and the report (ADR-030)
- [`docs/phase-6.10.md`](docs/phase-6.10.md) — **meaning**: scoped samples, the mapping
  interview (model proposes, person confirms, code compiles), and edit / typed delete
  everywhere (ADR-032, ADR-033)
- [`docs/phase-6.11.md`](docs/phase-6.11.md) — **nothing slips**: coverage of every
  requirement, a fail-closed finalize gate with an attestation, decision reasons, three
  independent lenses at stage 8 merged by code, a benchmark harness (ADR-034…036)
- [`docs/phase-6.12.md`](docs/phase-6.12.md) — **one front door**: a single place an
  administrator says what to check in their own words, and one scope vocabulary across
  the API, both consoles and the documents
- [`docs/phase-6.13.md`](docs/phase-6.13.md) — **the loop closes**: fifteen silent defects
  repaired, the author of an observation sees what became of it, findings carry their
  origin, judgment checks finished, a controlled example library for the model, and a
  replay that replays
- [`docs/model-context.md`](docs/model-context.md) — **what reaches the model**: the
  register of every field a person can write, which prompt block it lands in, which
  stages read it, the cap that applies, and whether code or the model acts on it
- [`docs/phase-6.14.md`](docs/phase-6.14.md) — **the artifacts belong together**: an
  artifact match check before any model call that a person accepts with a reason, the credit
  date resolved by label, every field saying what it does to a run, tooltips on by
  default, and the theme locked
- [`docs/phase-7.md`](docs/phase-7.md) — **real-world fit**: the dormant phase that runs
  on the machine holding the real files, only when asked (ADR-019)
- [`e2e/README.md`](e2e/README.md) — **browser tests**: what they cover, how to run them, and the conventions that keep them deterministic
- [`docs/decisions.md`](docs/decisions.md) — architectural decision records (append-only)
- [`docs/llm-privacy.md`](docs/llm-privacy.md) — what may and may not reach the LLM, the cache, fixture policy
- [`docs/deployment.md`](docs/deployment.md) — running it: docker-compose, `.env`, volumes, retention
- [`docs/glossary.md`](docs/glossary.md) — OSL, DIRT, waterfall, req_type, named value, trace, finding…
- [`docs/session-log.md`](docs/session-log.md) — working journal (read first / write last)
- [`standards/`](standards/README.md) — coding standards and git rules
- [`docs/benchmarks/README.md`](docs/benchmarks/README.md) — golden-set accuracy numbers.
- [`mock/README.md`](mock/README.md), [`user-ui/README.md`](user-ui/README.md),
  [`admin-ui/README.md`](admin-ui/README.md), [`src/greenlight_ai/README.md`](src/greenlight_ai/README.md),
  [`tests/README.md`](tests/README.md), [`scripts/README.md`](scripts/README.md)

## License

Internal project — proprietary; see [`LICENSE`](LICENSE).

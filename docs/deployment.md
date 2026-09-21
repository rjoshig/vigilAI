# Deployment

How Greenlight AI runs. Target: **one Linux host running docker-compose** (design.md
"Architecture"), behind a reverse proxy that terminates TLS. This page will fill in as the
phases land; sections marked `TODO(human)` need in-house facts.

## 1. Requirements

- Docker + docker-compose (Docker Desktop on the Mac dev box).
- Network reach from the `worker` container to the in-house LLM endpoint.
- Python 3.10 and Node 20 only for local, non-container development.

## 2. Configuration — `.env`

Every service reads settings from the environment. `cp .env.example .env` and edit; the
file is gitignored and never contains customer data.

| Var | Purpose | Default |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` (also vLLM, TGI, Ollama, gateways) · `anthropic` · `mock` | `mock` |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Endpoint, key, model. Switching model = edit + worker restart | — |
| `LLM_MAX_TOKENS`, `LLM_TEMPERATURE_PCT`, `LLM_TIMEOUT_S` | Per-call limits; temperature stays 0 and is whole percent (ADR-073 — the float `LLM_TEMPERATURE` is deprecated and read by the CLI alone) | 2000 / 0 / 120 |
| `LLM_MAX_CONCURRENCY` | Calls in flight per worker | 4 |
| `LLM_MAX_TOKENS_PER_RUN` | Budget; a run that exceeds it stops and is flagged | — |
| `LLM_LOG_PROMPTS` | Log prompt text. **Never true in production** | `false` |
| `LLM_PROMPT_VERSION` | Part of every cache key | 1 |
| `DATABASE_URL`, `POSTGRES_*` | Postgres connection | compose defaults |
| `GREENLIGHT_AI_DATA_DIR` | The shared volume mount (uploads, reports, PDFs) | `/data` in containers |
| `GREENLIGHT_AI_RETENTION_DAYS` | Purge window | 90 |
| `GREENLIGHT_AI_MAX_UPLOAD_MB` | Upload size limit | 50 |
| `GREENLIGHT_AI_API_URL` | Where the UIs proxy `/api/*` | `http://api:8000` |
| `GREENLIGHT_AI_CORS_ORIGINS` | Allowed browser origins for the API, comma-separated. **Set it on any real hostname**: unset means the two localhost ports, and a deployment that leaves it has its own UIs refused. Read at startup, never from the console | localhost dev origins |
| `GREENLIGHT_AI_DRAFT_DAYS` | How long an unsubmitted draft is kept (ADR-065) | 5 |
| `GREENLIGHT_AI_CHAT` | Ask the frozen report (ADR-068). **Off unless set**, so an install that upgrades gains no outbound model surface by accident. `chat.model` unset means it answers with `LLM_MODEL` | `false` |

Environment matrix (design.md "Switching environments"):

| Environment | `LLM_PROVIDER` | `LLM_BASE_URL` | `LLM_MODEL` |
| --- | --- | --- | --- |
| Mac dev, local | `openai` | Ollama OpenAI-compatible endpoint on localhost | a Gemma model |
| Mac dev, Claude | `anthropic` | Anthropic API | a Claude model |
| Tests and CI | `mock` | none | none |
| In-house production | `openai` or `anthropic` | internal gateway | in-house model |

## 3. Services (`docker-compose.yml`)

| Service | Image | Port | Notes |
| --- | --- | --- | --- |
| postgres | `postgres:16` | 5432 (dev only) | volume `pgdata` |
| api | `docker/api.Dockerfile` | 8000 | mounts `files:/data` |
| worker | `docker/worker.Dockerfile` | — | mounts `files:/data`; `--scale worker=N`; Chromium for PDF from Phase 5 |
| user-ui | `user-ui/Dockerfile` | 3000 | proxies `/api/*` to api |
| admin-ui | `admin-ui/Dockerfile` | 3001 | its own URL; proxies `/api/*` to api |

```bash
docker compose up --build            # first run; api applies Alembic migrations on start
docker compose up --scale worker=4   # more pipeline throughput (LLM-bound)
```

## 4. Reverse proxy and TLS

`TODO(human)`: nginx or Traefik in front of user-ui (:3000), admin-ui (:3001), and api
(:8000); TLS certificates from the in-house CA. Encrypted Docker volumes for `files` and
`pgdata` per the design doc "Security and PII".

## 5. Retention

A nightly worker task deletes runs past `runs.expires_at` (created + 90 days), their files
on the volume, and their rules / findings / stats. Aggregated usage stats are kept.
`scripts/purge.py --dry-run` (Phase 6) reports what would go. The same sweep prunes
definition versions beyond the ten listed (keeping any a live run names) and removes
sample workbooks no version references (ADR-029).

## 6. Scaling notes

The web tier is not the bottleneck; LLM throughput is. About 80 concurrent users is light
for Next.js + FastAPI on one host. Tune `worker` replicas × `LLM_MAX_CONCURRENCY` to what
the in-house model serves; the queue caps runs in flight and per-order-number repeats.
Expect 5–15 minutes per run on a mid-size model (150–200 small calls per OSL), to be
confirmed with a real OSL.

## 7. Checklist before go-live (Phase 6)

- [ ] `LLM_LOG_PROMPTS=false`; logs carry ids and counts only
- [ ] masked-column list populated in admin-ui
- [ ] TLS at the proxy; encrypted volumes
- [ ] retention window agreed with security / compliance (DIRT files with PII)
- [ ] load test at ~80 concurrent users
- [ ] parsers adapted to the real in-house layouts
- [ ] login decided: both switches on with the bootstrap password changed, or both off
      deliberately (see "Login and attribution" below)


## Choosing the database (ADR-017)

One setting decides, and nothing else in the code or the compose file changes:

```bash
DATABASE_URL=sqlite+pysqlite:///./data/greenlight-ai.db            # default; needs nothing
DATABASE_URL=postgresql+psycopg://greenlight_ai:greenlight_ai@postgres:5432/greenlight_ai
```

**SQLite** is right for a laptop, a demo, and a single-worker in-house pilot. It needs no
container and no server, so tests, migrations, the CLI, and one worker all run from a
checkout. It takes one writer at a time.

**Postgres** is right once several workers run at once, which is what
`docker compose up` starts. The compose file sets `DATABASE_URL` to the `postgres`
service for you.

Migrations are portable and run the same way against either:

```bash
alembic upgrade head        # the api container does this on start
```

The backend in use is logged once at startup by both the api and the worker, so a
deployment can always be checked rather than assumed.

## Pre-deployment checklist

Tick these on the machine that will run the service. Items marked **in-house** cannot
be done from a development checkout and are what Phase 6 hands to the platform team.

### Data and retention

- [ ] `DATABASE_URL` points at the intended backend, and the startup log line confirms
      it (ADR-017). Compose sets Postgres; anything else is SQLite by default.
- [ ] `alembic upgrade head` has run. The api container does this on start.
- [ ] `GREENLIGHT_AI_DATA_DIR` is a mounted volume, not a container-local path, or every
      uploaded file and frozen report disappears on restart.
- [ ] `python scripts/purge.py --dry-run` reports what you expect before the first real
      purge. The worker schedules a sweep every 24 hours by itself; no cron entry is
      needed.
- [ ] **in-house** A decision on whether DIRT files need a shorter window than the
      90-day default, recorded as an ADR (open question in `phase-plan.md`).

### Privacy

- [ ] `LLM_LOG_PROMPTS=false`. It exists for synthetic data on a developer machine, and
      the adapter logs a warning on every call while it is on.
- [ ] `LLM_PII_TRIPWIRE=true`. It scans every assembled prompt and refuses to send a
      match; a prompt already sent cannot be recalled.
- [ ] The masked-column list in the admin-ui covers every identifying column in the
      **real** DIRT layout. The shipped defaults cover the obvious ones and are a
      starting point, not an answer.
- [ ] **in-house** TLS terminates at the reverse proxy, and the Docker volumes are
      encrypted at rest. Confirm against the internal standard.
- [ ] **in-house** Security and compliance have signed off on retention and PII
      handling, recorded as an ADR.

### Login and attribution (ADR-022)

Login is built and ships **off**, so a development checkout behaves exactly as it
always has. Turning it on is a deployment decision, and these are the three parts of
it. Leaving any one undone is worse than leaving login off: a half-configured sign-in
looks like protection and is not.

- [ ] `GREENLIGHT_AI_ADMIN_AUTH=true` and `GREENLIGHT_AI_USER_AUTH=true`. The admin
      console is the one that reaches every future run, so turn it on first if you
      stage the change.
- [ ] **The bootstrap password is changed.** The API refuses to serve a non-loopback
      deployment while it still stands, which is deliberate: the failure to start is
      the reminder.
- [ ] At least two administrator accounts exist. One is a lockout waiting to happen.
- [ ] TLS terminates at the proxy, so the session cookie is `Secure`. A cookie sent
      over plain HTTP is a session anyone on the path can take.
- [ ] Everyone has changed their password at first sign-in; the product forces this and
      it is worth confirming nobody is still on an administrator-set one.
- [ ] Spot-check the audit log: sign-in, sign-out, a failed sign-in and a review
      decision should each name the person. That is the question this phase exists to
      answer, and the check takes a minute.

A programme's **second approver** switch depends on this: with login off it stands down
entirely, because both people would be the same account (ADR-036). Turn login on before
relying on it.

With login off, every action is attributed to the seeded placeholder account rather
than to nobody, so the frozen report still names a submitter and a reviewer. That is
attribution, not authentication, and it should not be mistaken for it.

### The model

- [ ] `LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_MODEL` point at the in-house gateway, and
      `/health` is green.
- [ ] `LLM_MAX_TOKENS_PER_RUN` is set to something the finance owner has seen.
- [ ] Guided or JSON-schema decoding is enabled if the serving stack supports it; vLLM
      does, and it removes most format errors.
- [ ] **in-house** `python scripts/golden_set.py --provider openai --out
      docs/benchmarks/phase-2.md` has been run against that model and the numbers
      recorded. Expect a prompt-version bump afterwards.

### Scale

- [ ] Worker replicas × `LLM_MAX_CONCURRENCY` is below what the model endpoint will
      serve. Two workers at concurrency 4 is eight in-flight calls.
- [ ] `python scripts/load_test.py --runs 50 --workers 8` passes locally. It measures
      the code paths, not production throughput; the real number needs the real model.
- [ ] **in-house** A load test at the expected concurrency, with the results recorded.

### Reports

- [ ] A finalized run downloads as a PDF, and the PDF contains the expanded findings
      rather than a page of headings. `pip install -e ".[pdf]" && playwright install
      chromium` in the worker image; `GET /runs/{id}` reports `pdf_available` so the UI
      can say so before anyone clicks.
- [ ] After fixing anything in the report template or the PDF renderer, delete the
      stored `data/reports/*.pdf` files. They are a cache of a rendering and will not
      update themselves. The `.html` files are the frozen record and are **never**
      deleted or regenerated (ADR-005).

### Files

- [ ] **in-house** One real OSL, config, and report set runs end to end with only the
      parser implementations changed, and a synthetic fixture mirroring each real
      layout's *shape* has been added to `tests/fixtures/` (never the real file).

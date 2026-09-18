# Deployment

How vigilAI runs. Target: **one Linux host running docker-compose** (design.md
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
| `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_TIMEOUT_S` | Per-call limits; temperature stays 0 | 2000 / 0 / 120 |
| `LLM_MAX_CONCURRENCY` | Calls in flight per worker | 4 |
| `LLM_MAX_TOKENS_PER_RUN` | Budget; a run that exceeds it stops and is flagged | — |
| `LLM_LOG_PROMPTS` | Log prompt text. **Never true in production** | `false` |
| `LLM_PROMPT_VERSION` | Part of every cache key | 1 |
| `DATABASE_URL`, `POSTGRES_*` | Postgres connection | compose defaults |
| `VIGILAI_DATA_DIR` | The shared volume mount (uploads, reports, PDFs) | `/data` in containers |
| `VIGILAI_RETENTION_DAYS` | Purge window | 90 |
| `VIGILAI_MAX_UPLOAD_MB` | Upload size limit | 50 |
| `VIGILAI_API_URL` | Where the UIs proxy `/api/*` | `http://api:8000` |
| `VIGILAI_CORS_ORIGINS` | Allowed origins (the two UI URLs) | localhost dev origins |

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
`scripts/purge.py --dry-run` (Phase 6) reports what would go.

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

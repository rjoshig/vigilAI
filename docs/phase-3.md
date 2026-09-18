# Phase 3 — Web app

**Status:** planned. **Goal:** the pipeline running as a service: docker-compose with
Postgres (data + queue), the FastAPI api, Procrastinate workers, and the user-ui. Effort
~3 weeks. Depends on Phase 2.

## Scope

**Data + queue**
- [ ] `db/models.py`: every table in `design.md` "Data model" (`users` created, unused —
      ADR-008), SQLAlchemy 2, Alembic migrations (`db/migrations/`), applied on api start.
- [ ] `llm/cache.py` backend → `llm_cache` table; `llm/calls.py` → `llm_calls`.
- [ ] `worker/app.py`: Procrastinate app; `worker/tasks.py`: `run_pipeline(run_id)` with
      3 retries + backoff, then `failed` with the error; per-order-number queued-run cap.
- [ ] Stage idempotency against `run_stages` (resume, never redo LLM work).

**API (`/api/v1`)**
- [ ] `POST /runs` (multipart; `.docx`/`.json`/`.xlsx` only, size limit, content-type
      check; fingerprint → existing run unless `rerun_reason`), `GET /runs`, `GET /runs/{id}`
      (status, stage, queue position).
- [ ] `GET/PUT /runs/{id}/requirements` (rules + traces; edits bump `rules.version`),
      `POST /runs/{id}/recheck` (stages 5–7 only).
- [ ] `GET /runs/{id}/findings`, `PATCH /findings/{id}` (OK / Not OK + comment; confirmed /
      false positive / accepted risk).
- [ ] `POST /runs/{id}/clone`, `GET /runs/{id}/stats`, `GET /configs`, `GET /configs/{id}`.
- [ ] The **single auth dependency** on every router (no-op in v1, ADR-008); `audit_log`
      writes for view / download / review / edit.
- [ ] `docker/api.Dockerfile`, `docker/worker.Dockerfile` real; `docker compose up` works.

**user-ui** (`standards/frontend.md`)
- [ ] Scaffold: Next.js 15, TypeScript strict, Tailwind 3, ESLint 8, Prettier, Vitest;
      theme tokens and `components/ui/` from compare-file ui2; `/api/*` rewrite proxy;
      `user-ui/Dockerfile`.
- [ ] Screens from the Phase 1 mock: New run (with duplicate-inputs dialog), Runs
      (polling every 3 s), Review (traceability matrix, findings, evidence panel, OK / Not
      OK, edit + Re-check), Run stats, Config history. The Final report screen lands in
      Phase 5.
- [ ] Vitest coverage of the review flow, matrix filters, and the API client.

## Acceptance criteria

1. `docker compose up --build` starts all five containers; a run submitted from user-ui
   goes queued → running → needs_review with live stage progress, on synthetic inputs and
   `LLM_PROVIDER=mock`.
2. Duplicate inputs return the existing run; a `rerun_reason` creates a new one and is
   visible in stats and `audit_log`.
3. Re-check after a rule edit changes findings in seconds with zero LLM calls (asserted).
4. Killing a worker mid-run and restarting resumes at the last good stage.
5. API gates + user-ui gates clean; CI dispatch green.

## Out of scope

admin-ui, configurable checks, the final report, PDF.

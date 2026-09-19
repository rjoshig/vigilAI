# Phase 3 — Web app

**Status:** ✅ **complete** (2026-09-18), with one criterion partly met: everything is
built and proven against SQLite, but `docker compose up` itself has not been run because
Docker is not available on the development machine.

**Goal:** the pipeline running as a service: docker-compose, the database holding both
data and the job queue, the FastAPI api, the workers, and the user-ui. Effort ~3 weeks.
Depends on Phase 2.

## Scope · ✅ complete

**Data + queue** · ✅ complete
- [x] `db/models.py`: every table in `design.md` "Data model" (`users` created, unused —
      ADR-008), SQLAlchemy 2, Alembic migration in `db/migrations/`, applied on api start.
      Portable across SQLite and Postgres, selected by `DATABASE_URL` (ADR-017).
- [x] `db/cache.py`: the `llm_cache` table behind the Phase 2 `CacheBackend` interface;
      `record_calls` writes `llm_calls` (ids and counts only, ADR-003).
- [x] `db/queue.py`: the `jobs` table, claimed with `FOR UPDATE SKIP LOCKED` on Postgres
      and a guarded `UPDATE` on SQLite; backoff, stale-claim recovery, queue position.
      Procrastinate is dropped because it is Postgres-only (ADR-017).
- [x] `worker/app.py`: the polling loop with `run_pipeline`, `recheck`, and `purge`
      tasks, 3 retries with backoff, then `failed` with the error shown in the UI;
      per-order-number queued-run cap enforced in the API.
- [x] Stage idempotency against `run_stages` (resume, never redo LLM work).

**API (`/api/v1`)** · ✅ complete
- [x] `POST /runs` (multipart; `.docx`/`.json`/`.xlsx` only, size limit, content-type
      check; fingerprint → existing run unless `rerun_reason`), `GET /runs`,
      `GET /runs/{id}` (status, stage, queue position).
- [x] `GET/PUT /runs/{id}/requirements` (rules + traces; edits bump `rules.version` and
      queue a re-check), `POST /runs/{id}/recheck` (stages 5–7 only, zero LLM calls).
- [x] `GET /runs/{id}/findings`, `PATCH /findings/{id}` (confirmed / false positive /
      accepted risk + comment), `POST /runs/{id}/findings/bulk-ok` for low severity.
- [x] `POST /runs/{id}/clone`, `GET /runs/{id}/stats`, `GET /configs`, `GET /configs/{id}`.
- [x] The **single auth dependency** on every router (no-op in v1, ADR-008); `audit_log`
      writes for create / review / edit / re-check / duplicate-blocked.
- [x] `docker/api.Dockerfile`, `docker/worker.Dockerfile` real; compose updated.
      **Unverified:** `docker compose up` has not been run — Docker is not available on
      the development machine. The file parses as valid YAML and declares all five
      services, and `user-ui/Dockerfile` builds the standalone output.

**user-ui** (`standards/frontend.md`) · ✅ complete
- [x] Scaffold: Next.js 15, TypeScript strict, Tailwind 3, ESLint 8, Prettier, Vitest;
      theme tokens matching the ui2 palette and the Phase 1 mock; `/api/*` rewrite proxy;
      `user-ui/Dockerfile` (standalone output).
- [x] Screens from the Phase 1 mock: New run (with the duplicate-inputs dialog), Runs
      (polling every 3 s, and only while something is queued or running), Review
      (traceability matrix, findings, evidence panel, OK / Not OK with comments, bulk-OK,
      Re-check, Clone), Run stats, Config history. The Final report screen lands in
      Phase 5.
- [x] Vitest coverage of the matrix join, its status rules, and the API client's error
      handling. 35 tests; no network in any of them.

## Acceptance criteria · 🟡 in progress

1. [~] A run submitted through the API goes queued → running → needs_review with live
   stage progress, on synthetic inputs and `LLM_PROVIDER=mock`. Proven end to end
   against SQLite in `tests/api/test_end_to_end.py` and by hand against a live uvicorn
   and worker. **Outstanding:** `docker compose up --build` itself, because Docker is
   not available on the development machine. The compose file parses as valid YAML and
   declares all five services; both Dockerfiles are real.
2. [x] Duplicate inputs return the existing run; a `rerun_reason` creates a new one and
   is visible in `audit_log`. A check-version change invalidates the shortcut.
3. [x] Re-check after a rule edit changes findings in seconds with zero LLM calls
   (asserted: no new uncached `llm_calls` rows).
4. [x] Killing a worker mid-run and restarting resumes at the last good stage
   (asserted: a stale claim is reclaimed, and the resumed run makes no further calls).
5. [~] API gates clean (`black`, `flake8`, `mypy --strict`, `pytest`: 602 tests) and
   user-ui gates clean (`lint`, `typecheck`, `format:check`, `test`, `build`).
   **Outstanding:** a CI dispatch, which is manual-only by ADR-012.

## Out of scope

admin-ui, configurable checks, the final report, PDF.

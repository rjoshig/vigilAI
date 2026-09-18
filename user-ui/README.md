# user-ui

The associate-facing app: submit a run, watch it execute, review the findings.
Next.js 15 App Router, TypeScript strict, Tailwind 3, Vitest (ADR-011). Serves on
**:3000**; `admin-ui` is a separate app on :3001 and the two never import each other.

## Screens

| Route              | What it does                                                                                                   |
| ------------------ | -------------------------------------------------------------------------------------------------------------- |
| `/runs`            | History with filters, queue position, live stage progress. Polls every 3 s while anything is queued or running |
| `/runs/new`        | The upload form, with the duplicate-inputs dialog that asks for a re-run reason                                |
| `/runs/[id]`       | Review: the traceability matrix, the findings, the evidence panel, OK / Not OK with comments, re-check         |
| `/runs/[id]/stats` | Stage timings, model calls, tokens, cache hits                                                                 |
| `/configs`         | Captured configs by configuration ID and version                                                               |

The final report screen lands in Phase 5.

## Running it

```bash
npm install
npm run dev                 # http://localhost:3000
```

The app talks to `/api/*`, which `next.config.mjs` rewrites to `VIGILAI_API_URL`
(default `http://127.0.0.1:8000`), so the browser never meets CORS. Start the API with:

```bash
cd .. && uvicorn vigilai.api.app:get_app --factory --reload
cd .. && python -m vigilai.worker.app        # in another terminal
```

## Gates

All must be clean before a commit:

```bash
npm run lint
npm run typecheck
npm run format:check
npm test
npm run build
```

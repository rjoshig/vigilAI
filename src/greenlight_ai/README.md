# src/greenlight_ai — the Python package

One installable package; the api and the worker are two entry points over the same code.
No code lands here until Phase 2 (`docs/phase-plan.md`). The map below is the contract;
`docs/architecture.md` explains each row and `standards/python.md` the rules.

| Subpackage | Holds | Lands in |
| --- | --- | --- |
| `parsers/` | Protocols + implementations for the OSL (.docx), config (.json), and each report type (.xlsx); sample-row masking | Phase 2a |
| `rules/` | Canonical rule schema, normalizers, derived checks | Phase 2b |
| `llm/` | The one adapter: `LLMClient` Protocol, openai / anthropic / mock clients, factory, cache, call log, versioned prompts | Phase 2c |
| `pipeline/` | Stages 1–9 + orchestrator + resume | Phase 2d–2e |
| `checks/` | Per-`req_type` report checks, expression evaluator, compliance presence, reverse-pass scoping | Phase 2e |
| `cli.py` | `greenlight-ai run …` | Phase 2f |
| `db/` | SQLAlchemy models, Alembic migrations, session helpers | Phase 3 |
| `api/` | FastAPI app, routers, wire models, the single auth dependency | Phase 3 |
| `worker/` | Procrastinate app and tasks | Phase 3 |
| `report/` | Jinja2 final report, freeze, PDF | Phase 5 |

Dependencies point down: `api → db, worker`; `worker → pipeline, db`; `pipeline → parsers,
rules, llm, checks`; `checks → rules`; `llm → db`. `api` never imports `pipeline`.

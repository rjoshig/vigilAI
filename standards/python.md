# Python Standards

Applies to everything under `src/vigilai/` (parsers, rules, pipeline, checks, llm, db,
api, worker, report, cli) and the `tests/` suite. The tooling config (`pyproject.toml`,
`.flake8`) is authoritative for exact settings; this doc explains intent. Adapted from
`compare-file/standards/python.md`.

## Tooling contract

All three must be **clean before every commit**:

```bash
black .            # format       (line length 100)
flake8             # lint         (config in .flake8; flake8-bugbear enabled)
mypy src/          # type-check   (strict mode)
```

- **black** — line length 100, target py310–py312. Never hand-format around it.
- **flake8** — max line 100; `E203`/`W503` ignored (black owns those); `__init__.py` may
  keep unused imports (`F401`) for re-exports. Don't suppress `flake8-bugbear` without a
  reason in the code.
- **mypy** — `strict = true`. Tests are exempt from `disallow_untyped_defs` but should
  still be typed where practical.

## Language version

- **Python 3.10 is the floor and the pin** (ADR-010). `.python-version` pins 3.10.x; code
  must run on 3.10, 3.11, and 3.12.
- Don't use syntax or stdlib newer than 3.10: no `ExceptionGroup`/`except*`, no
  `typing.Self`, no `tomllib`, no PEP 701 nested-quote f-strings. `from __future__ import
  annotations` is fine and preferred for forward refs. `X | Y` unions are fine.

## Typing

- **Type hints on every function and method signature** — parameters and return.
- Prefer **frozen dataclasses with slots** for value objects: `@dataclass(frozen=True,
  slots=True)`. Use **Pydantic v2 models** only at boundaries: LLM output schemas, API
  request/response models, config loading.
- Use `typing.Literal` and module-level **type aliases** for small closed sets
  (`ReqType = Literal["criteria", "geography", ...]`, `Severity = Literal[...]`) instead of
  bare `str`.
- Use `typing.Protocol` for interfaces / pluggable behavior: the parsers (ADR-006) and the
  LLM client (ADR-004) are Protocols.
- No `Any` unless genuinely unavoidable. If you must `# type: ignore`, scope it to the line
  and say why.

## Docstrings & comments

- **Google-style docstrings on every public function, class, and module.** Include
  `Args:`, `Returns:`, `Raises:` where they apply.
- Reference the relevant **ADR** in the docstring when behavior encodes a decision.
- Comments explain **why**, not what.

## Core idioms (mandated)

- **Paths:** `pathlib.Path` everywhere.
- **Logging:** the `logging` module — **never `print()`** in library code. Log **ids and
  counts only**: never a sample row, a field value from a report, an OSL sentence, or a
  prompt (ADR-003). `LLM_LOG_PROMPTS` is the only switch that may log prompt text, and it
  exists for synthetic data only.
- **The LLM reads, code checks (ADR-001).** Any comparison of values, sets, intervals,
  operators, counts, or sequences is deterministic Python in `rules/`, `pipeline/`, or
  `checks/`. Never ask the model to compare numbers or do arithmetic. If a stage needs a
  judgment, it asks one narrow question and validates the JSON answer with a Pydantic schema.
- **One LLM entry point (ADR-004).** Only `vigilai.llm` talks to a model. Everything else
  calls `LLMClient.complete(system, user, schema)`. Provider, base URL, model, and limits
  come from the environment. No vendor SDKs; plain `httpx`.
- **Cache before every call (ADR-005).** The adapter looks up `llm_cache` by
  `sha256(content) + model + prompt version` before sending anything. A cache miss is the
  only path to the network. Every call writes an `llm_calls` row.
- **Prompts are versioned.** Each prompt template carries a version constant that is part of
  the cache key; bump it when the wording changes.
- **Parsers sit behind Protocols (ADR-006).** `OslParser`, `ConfigParser`, and one
  `ReportParser` per report type. The pipeline imports the Protocol, never a concrete class.
  Real file layouts arrive last and only in-house, so the first implementations are
  driven by the synthetic fixtures.
- **Streaming where it matters:** Excel report sheets can be large; use `openpyxl`
  read-only mode / chunked `pandas` reads rather than loading whole workbooks by default.
- **No magic numbers:** promote to module-level constants or config. Severity thresholds,
  the 0.7 confidence floor, retention days, and token budgets are named constants or env
  settings.
- **Pure functions where possible** — the stage functions take parsed inputs and return
  findings; side effects (DB, files, LLM) live at the edges.
- **CLI:** `argparse`; every option has help text. The CLI (Phase 2) is the first entry
  point and stays usable after the API lands.
- **Config:** JSON/env, **validated at load time, failing loudly** on bad input, with a clear
  message naming the offending key.
- **Concurrency is configurable:** `LLM_MAX_CONCURRENCY` and worker replica count are the
  knobs; never hardcode worker counts.

## Errors & exceptions

- Raise **specific** exception types (`ParseError`, `LLMError`, `CacheError`,
  `ConfigError`); never `raise Exception(...)`.
- **No bare `except:`** and no blanket `except Exception` that swallows. Catch the narrowest
  type; handle it or re-raise with context.
- A check that cannot be evaluated (a named value not found) is a **finding**, never a
  silent skip (`docs/design.md` "Configurable checks").

## Package structure (`src/vigilai/`)

| Subpackage | Holds | Depends on |
| --- | --- | --- |
| `parsers/` | Protocols + implementations for OSL (.docx), config (.json), report types (.xlsx); masking of sample rows | nothing internal |
| `rules/` | Canonical rule schema (Pydantic), normalizers (state names → codes, ranges → intervals), derived-check generation | nothing internal |
| `llm/` | `LLMClient` Protocol, `openai`/`anthropic`/`mock` clients, factory, cache, prompt templates with versions | `db/` (cache + llm_calls) |
| `pipeline/` | One module per stage 1–9, the orchestrator, resume logic | `parsers/`, `rules/`, `llm/`, `checks/` |
| `checks/` | Report checks per `req_type`, expression evaluator for admin-defined checks, compliance-rule presence | `rules/` |
| `db/` | SQLAlchemy models (the tables in `docs/design.md` "Data model"), Alembic migrations, session helpers | nothing internal |
| `api/` | FastAPI app, routers, Pydantic wire models, the single auth dependency (ADR-008) | `db/`, `worker/` (enqueue only) |
| `worker/` | Procrastinate app, task that runs the pipeline for a run id, retention purge | `pipeline/`, `db/` |
| `report/` | Jinja2 one-page HTML report, freeze, PDF via Playwright | `db/` |
| `cli.py` | Command-line entry point (`vigilai run …`) | `pipeline/` |

Keep the arrows pointing down: `api/` never imports `pipeline/`; `pipeline/` never imports
`api/`. `__init__.py` is for re-exports only.

## Testing

- **Write tests as you write code**, not at the end of a phase.
- **One test file per module:** `src/vigilai/rules/normalize.py` →
  `tests/rules/test_normalize.py`. Tests mirror the package layout.
- pytest with `--strict-markers --strict-config`; **`filterwarnings = ["error"]`** — a new
  warning fails the suite, so fix the cause.
- **Fixtures are synthetic only (ADR-003).** `tests/fixtures/` holds generated `.docx`,
  `.json`, `.xlsx` with invented customers, states, and thresholds. A real customer file,
  or anything derived from one, never enters the repo.
- **Tests never call a real LLM.** `LLM_PROVIDER=mock` returns canned JSON per prompt
  version; a test that needs a specific answer injects a fake `LLMClient`.
- **The golden set** (10–20 synthetic OSLs with known-correct rules) lives under
  `tests/fixtures/golden/` from Phase 2 and runs whenever a prompt or the model changes.
- Branch coverage is on (`pytest-cov`, source = `vigilai`). New code comes with meaningful
  coverage, not just line-hitting tests.

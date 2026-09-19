# tests/

pytest suite. Phase 0 has one smoke test (`test_package.py`) so the suite is green from day one.

- **Layout mirrors `src/vigilai/`:** `src/vigilai/rules/normalize.py` →
  `tests/rules/test_normalize.py`. One test file per module.
- **Synthetic fixtures only** (`fixtures/`), never a real customer file (ADR-003).
- **No real LLM:** `LLM_PROVIDER=mock` or an injected fake `LLMClient`. No network.
- `filterwarnings = error`: a new warning fails the suite; fix the cause.
- Shared helpers go in `tests/_helpers.py` once they exist (compare-file pattern).

Run: `pytest` (config in `pyproject.toml`). Coverage: `pytest --cov`.

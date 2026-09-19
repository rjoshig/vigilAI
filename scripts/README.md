# scripts/ — developer tooling (not shipped to production)

| Script | Purpose | Since |
| --- | --- | --- |
| `check_docs.sh` | Docs integrity: relative links resolve, every `docs/` file is indexed in `README.md`. Run before every docs commit; CI's `docs` job runs it too. | Phase 0 |
| `generate_fixtures.py` | Planned: build the **synthetic** OSL `.docx`, config `.json`, and report `.xlsx` fixtures under `tests/fixtures/` from a spec file. Never derived from real customer files (ADR-003). | Phase 2 |
| `golden_set.py` | Planned: run the golden set (10–20 synthetic OSLs with known-correct rules) through extraction and print accuracy; run whenever the model or a prompt changes. | Phase 2 |
| `purge.py` | Planned: the 90-day retention purge (`runs.expires_at`), also scheduled nightly. | Phase 6 |

Scripts are `bash` with `set -euo pipefail` (shellcheck clean) or Python following
[`standards/python.md`](../standards/python.md).

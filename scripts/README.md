# scripts/ — developer tooling (not shipped to production)

| Script | Purpose | Since |
| --- | --- | --- |
| `check_docs.sh` | Docs integrity: relative links resolve, phase-doc status markers match their checkboxes, each app's Guide is current with its training document, and every `docs/` file is indexed in `README.md`. Run before every docs commit; CI's `docs` job runs it too. | Phase 0 |
| `build_guides.py` | Builds each app's in-product **Guide** from the sections its training document marks, into `lib/guide.generated.ts` (ADR-050). One source per audience: edit the document, run this, commit both. `--check` fails instead of writing, which is how `check_docs.sh` and `tests/docs/test_guides.py` catch a document edited without a rebuild. | Phase 6.19b |
| `update_phase_status.py` | Derives the `· ✅ / 🟡 / ⬜` marker on every phase-doc section from the checkboxes beneath it. `--check` fails instead of writing. | Phase 0 |
| `generate_fixtures.py` | Planned: build the **synthetic** OSL `.docx`, config `.json`, and report `.xlsx` fixtures under `tests/fixtures/` from a spec file. Never derived from real customer files (ADR-003). | Phase 2 |
| `golden_set.py` | Planned: run the golden set (10–20 synthetic OSLs with known-correct rules) through extraction and print accuracy; run whenever the model or a prompt changes. | Phase 2 |
| `purge.py` | Planned: the 90-day retention purge (`runs.expires_at`), also scheduled nightly. | Phase 6 |

Scripts are `bash` with `set -euo pipefail` (shellcheck clean) or Python following
[`standards/python.md`](../standards/python.md).

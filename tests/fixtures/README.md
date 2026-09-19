# tests/fixtures — synthetic only

Every file here is **generated** by `scripts/generate_fixtures.py` (Phase 2) from a spec of
invented customers, states, attributes, and thresholds. Nothing is derived from, or
resembles, a real customer's OSL, config, or report (ADR-003).

Planned layout:

```
fixtures/
├── spec/           # the generator specs (JSON)
├── basic/          # one OSL .docx + config .json + report .xlsx set + expected findings
├── golden/         # 10–20 OSLs with known-correct rules (extraction accuracy benchmark)
└── real/           # gitignored; in-house only (Phase 6); never committed
```

`.gitignore` blocks `*.docx` / `*.xlsx` everywhere except under this directory as a backstop.

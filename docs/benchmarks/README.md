# Benchmarks

Accuracy numbers for the pipeline, recorded whenever a prompt or the model changes
(`docs/llm-privacy.md`, ADR-014). Produced by `scripts/golden_set.py`, which scores the
pipeline against the synthetic golden set: each case carries its own oracle in
`tests/fixtures/manifest.json`, so the expected answer travels with the fixture.

| File | Provider | What it records |
| --- | --- | --- |
| [`phase-2-synthetic.md`](phase-2-synthetic.md) | `synthetic` | The scripted stand-in. Proves the pipeline's code paths, not a model's reading ability |
| `phase-2.md` | a real model | **Not yet produced.** Phase 2 acceptance criterion 2, deferred by ADR-014 |

Regenerate:

```bash
python scripts/golden_set.py --out docs/benchmarks/phase-2-synthetic.md
python scripts/golden_set.py --provider openai --out docs/benchmarks/phase-2.md
```

The synthetic numbers being perfect is expected and is **not** evidence that extraction
works: the scripted stand-in reads the fixtures the way a competent model would, so a
100% score means the pipeline draws the right conclusions from right answers. Only the
real-model run measures whether a model gives right answers in the first place.

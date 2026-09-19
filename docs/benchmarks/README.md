# Benchmarks

Accuracy numbers for the pipeline, recorded whenever a prompt or the model changes
(`docs/llm-privacy.md`, ADR-014). Produced by `scripts/golden_set.py`, which scores the
pipeline against the synthetic golden set: each case carries its own oracle in
`tests/fixtures/manifest.json`, so the expected answer travels with the fixture.

| File | Provider | What it records |
| --- | --- | --- |
| [`phase-2-synthetic.md`](phase-2-synthetic.md) | `synthetic` | The scripted stand-in. Proves the pipeline's code paths, not a model's reading ability |
| [`phase-2-real-model.md`](phase-2-real-model.md) | `anthropic` | The first real model, after the prompt hardening of ADR-028. 12 / 12 on the synthetic set |
| `phase-2.md` | the in-house gateway, real files | **Not yet produced.** Deferred to the target environment (ADR-028) |

Regenerate:

```bash
python scripts/golden_set.py --out docs/benchmarks/phase-2-synthetic.md
python scripts/golden_set.py --provider anthropic --out docs/benchmarks/phase-2-real-model.md
python scripts/golden_set.py --provider openai --out docs/benchmarks/phase-2.md   # in-house
```

The synthetic numbers being perfect is expected and is **not** evidence that extraction
works: the scripted stand-in reads the fixtures the way a competent model would, so a
100% score means the pipeline draws the right conclusions from right answers. Only the
real-model run measures whether a model gives right answers in the first place.

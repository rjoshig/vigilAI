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
| [`phase-6.11-single.md`](phase-6.11-single.md) | `synthetic` | Stage 8 as it ships: one second opinion (`--lenses single`) |
| [`phase-6.11-lenses.md`](phase-6.11-lenses.md) | `synthetic` | Stage 8 with the three lenses (`--lenses delivery,compliance,requirements`) |
| [`phase-6.21-anomaly.md`](phase-6.21-anomaly.md) | none | The anomaly check, which makes no model call at all. Produced by `scripts/anomaly_benchmark.py` |

Regenerate:

```bash
python scripts/golden_set.py --out docs/benchmarks/phase-2-synthetic.md
python scripts/golden_set.py --provider anthropic --out docs/benchmarks/phase-2-real-model.md
python scripts/golden_set.py --provider openai --out docs/benchmarks/phase-2.md   # in-house

# The variant switch: run it twice and compare (Phase 6.11b, ADR-034).
python scripts/golden_set.py --lenses single --out docs/benchmarks/phase-6.11-single.md
python scripts/golden_set.py --lenses delivery,compliance,requirements \
  --out docs/benchmarks/phase-6.11-lenses.md
```

## What each report says

Three numbers, and they answer different questions. **Precision and recall** say how
often the tool is right about what it looked at. **Coverage** says how much it looked
at: a run that finds nothing because it compared nothing scores perfectly on the first
two and is worthless (ADR-035). **Model calls** is what the accuracy cost. A variant is
worth adopting when it improves the first two without making the third unaffordable.

## The lens comparison, and why it does not settle anything yet

`phase-6.11-single.md` and `phase-6.11-lenses.md` are the same fifteen cases under the
two stage-8 variants. They are identical on every accuracy number — 15 / 15, 100%
precision, 100% recall, the same coverage — and differ only in cost: 323 model calls
against 345, about 7% more.

**That result is not evidence the lenses are pointless.** The scripted stand-in returns
the same canned agreement to every lens, because it is a script and not a reader. So
this comparison measures the fixtures, exactly as ADR-028 warned. The lenses exist to
catch a finding one stance waves through and another stops on, and a stand-in that
holds no stance cannot produce that disagreement.

What it does establish, and what it was run for:

- The three lenses cost about 7% more calls on this set, not three times more, because
  only high-severity findings are read twice and the cache carries the rest.
- Turning them on changes no finding the pipeline produces when the readers agree, so
  the switch is safe to flip and safe to flip back.
- Every code path is exercised: three prompts, the merge, the proposal path, the
  coverage reader.

**`LLM_VERIFY_LENSES` therefore stays at `single`.** The comparison that decides it runs
on the target environment against the in-house gateway and real files, alongside the
Phase 2 benchmark that is deferred there for the same reason (ADR-028, ADR-034). Until
then, changing what reviewers see would be a change made on argument rather than
evidence.

The synthetic numbers being perfect is expected and is **not** evidence that extraction
works: the scripted stand-in reads the fixtures the way a competent model would, so a
100% score means the pipeline draws the right conclusions from right answers. Only the
real-model run measures whether a model gives right answers in the first place.

The anomaly check is measured on its own, because it makes no model call and so has
nothing to do with a prompt or a provider:

```bash
python scripts/anomaly_benchmark.py --out docs/benchmarks/phase-6.21-anomaly.md
```

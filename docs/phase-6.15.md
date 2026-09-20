# Phase 6.15 — A compliance rule should survive being spelled differently

**Status:** ⬜ **not started** — specified 2026-09-21 from a question the user asked and
a measurement that answered it. **The approach is deliberately left open**; this
document states the problem, the evidence, the constraint the answer has to satisfy,
and three candidate shapes. It is not yet a build plan.

## The question that started it

> *From the admin console, compliance rules are used by the LLM I thought, because
> there is no deterministic way to check compliance rules are available in OSL and
> config both, correct? I see a note that "Evaluated by code on every run; nothing here
> is sent to the model", but why would that be?*

The note is accurate. `pipeline/s6_reverse.py` opens with *"Stage 6: the scoped reverse
pass. Pure code, no LLM call."* A compliance rule is two fields, and the whole check is
one line:

```python
matching = [b for b in config.blocks if rule.json_path_contains in b.json_path]
if not matching:
    → "rule_missing_in_config", severity HIGH
```

A **substring match on the configuration's JSON paths**, plus an optional scalar
comparison when the path resolves to one. Nothing about a compliance rule has ever
reached a prompt.

## What that costs, measured

Three seeded rules — OFAC suppression, deceased suppression, opt-out list — against
configurations that implement exactly those three controls under names a different
customer might use.

| Configuration shape | Rules matched | False **HIGH** findings |
| --- | --- | --- |
| Exactly as the rules expect | 3 of 3 | 0 |
| `opt_out` where the rule says `optout` | 2 of 3 | 1 |
| Grouped under `exclusions` rather than `suppressions` | 0 of 3 | **3** |
| Vendor names: `sdn_screening`, `mortality`, `dnc_list` | 0 of 3 | **3** |
| `suppressions.lists.ofac` — the same words, one level deeper | 0 of 3 | **3** |
| Genuinely absent | 1 of 3 | 0 — the two it reports are really missing |

The last row matters as much as the others: **the check is not broken.** Where the
naming matches it is exact, free, reproducible, and explainable to an auditor — *"path
`suppressions.ofac` is `false`; the rule expects `true`."* That is worth keeping.

The row above it is the sharpest. `suppressions.lists.ofac` does not contain the
substring `suppressions.ofac`, so **one extra level of nesting turns three correct
controls into three high-severity findings that are wrong**. Not a different vendor,
not a different vocabulary — the same words, one level deeper.

## The defect, stated precisely

A compliance rule that finds no matching path fires at **high severity**, and it cannot
distinguish two situations that mean opposite things:

1. **The configuration does not implement the control.** A real finding, and a serious
   one.
2. **The configuration implements it under a name the rule does not know.** A false
   positive, at the highest severity the tool has.

This is the same shape as the credit-date defect closed in 6.14b: *a presence test that
cannot tell absence from "spelled differently."* One layer up, and with worse
consequences, because a high-severity compliance finding is the kind a reviewer escalates.

## What the premise gets wrong, and it matters

The question assumed the product keeps semantics away from the model on principle. It
does not. `CheckKind = Literal["expression", "judgment"]`: a **judgment check** already
shows the model named values and an instruction, the model answers, and **code sets the
severity** (ADR-039).

So the rule is not "nothing semantic reaches the model". It is ADR-001: **the model
reads and judges meaning; code does every comparison.** Judgment checks honour that.
Compliance rules simply never got the judgment path — which is an omission, not a
decision.

## The constraint any answer has to satisfy

**The model must never decide whether a delivery is compliant.** It may answer a narrow,
checkable question — *where, if anywhere, is this implemented* — and code turns the
answer into a severity. A design where the model returns "compliant: yes" is out of
scope however it is dressed, because that is a comparison, and comparisons are code's
(ADR-001).

Two further constraints from what is already built:

- **Nothing new activates without a person** (ADR-021). A location the model proposes is
  a proposal.
- **Do not add a seventeenth surface.** Phase 6.12 existed because sixteen places to
  tell the tool something was the main obstacle to somebody new being useful. If
  compliance rules gain examples, they should use the shape 6.13d already defines —
  `given` → `answer`, schema-validated, capped — rather than a new vocabulary.

## Three candidate shapes

Listed for discussion. **None is chosen.**

### A — Deterministic first, the model as a locator, code decides

```
compliance rule
  ├─ path matches       → code compares            → finding, exactly as today
  └─ path finds nothing → ask the model, once:
        "does anything in this configuration implement <rule + its examples>?"
        ├─ no, with confidence  → rule_missing_in_config, HIGH   (as today)
        ├─ yes, at <path>       → review severity: "implemented at a path this rule
        │                          does not name — confirm, and the path is added"
        └─ unsure               → review severity, and it says so
```

The model is asked only when the cheap check fails, so the common case costs nothing. A
confirmed location can be written back onto the rule — through the training queue, not
silently — so the next run matches deterministically and the model is consulted once per
customer per rule rather than every run.

**Attraction:** keeps everything good about today, removes the false HIGH, and
self-corrects.
**Cost:** a new finding state to explain, and a write-back path to design.

### B — A rule carries what it looks like in each artifact

The user's second suggestion: a rule states what it looks like in the OSL, what it looks
like in the configuration JSON, and what if anything to check in a report.

Part of this exists. **Validation guides** and **meaning entries** already map
OSL ↔ configuration path ↔ report cell — but both are anchored on a *report cell*, and a
compliance rule is anchored on a *configuration path* and often has no report at all. So
the gap is real rather than an unused feature.

**Attraction:** the examples make the rule legible to a person as well as to a model.
**Cost:** it is the seventeenth-surface risk in its purest form. Needs to reuse 6.13d's
example shape or it will not be worth what it costs to learn.

### C — Broaden the match deterministically before reaching for the model

Path-segment matching rather than substring, the alias table applied to path segments, a
configurable list of synonyms per rule. No model at all.

**Attraction:** stays entirely in code; cheapest to build and to explain.
**Cost:** it is the same brittleness with a bigger dictionary. The measurement suggests
it would fix the `opt_out` row and the nesting row, and do nothing for vendor names —
which is the row a real customer most often is.

**The pragmatic reading:** C is worth doing regardless, because it is cheap and it
removes two of the five failure shapes. A closes the remaining gap. They are not
alternatives.

## What to settle before this becomes a build plan

- [ ] Is a model-located match a **finding** or a **confirmation prompt**? Review
      severity plus write-back is the current leaning, because it self-corrects.
- [ ] Does a confirmed location amend the rule **automatically or through the training
      queue**? ADR-021 points at the queue.
- [ ] **Run statistics should say which engine answered.** When a rule is decided by
      code and when it is decided after a model call, the run's statistics should
      distinguish them, so the cost and the reliability of each path are visible rather
      than inferred. This is wanted whichever shape is chosen.
- [ ] Does the same problem apply to **programme rules and checks**? They are authored
      the same way and have not been measured.
- [ ] How does scope interact — global rules, delivery-programme rules, and the
      per-submission context — when the model is asked to locate something?

## Not in scope

**Letting the model decide compliance.** See "The constraint any answer has to satisfy".

**Rewriting the deterministic check.** It is correct where naming matches, and the
measurement says so. Whatever is built goes *behind* it, not instead of it.

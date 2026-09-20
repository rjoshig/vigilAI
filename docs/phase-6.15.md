# Phase 6.15 — A compliance rule should survive being spelled differently

**Status:** ✅ **complete** — 2026-09-21. Specified from a question the user asked and a
measurement that answered it. **Options C and A are both built**; B is not, and the
open questions at the foot of this document are answered where the build answered them.

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

**Measured in 6.16d, and the answer was no.** Named values were measured the way
compliance rules were. They are brittle in the same way — `Delivered_count` did not
resolve against a pointer configured as `Delivered count` — but the **consequence is
opposite**: an unresolvable pointer produces `could_not_evaluate` at *review* severity,
an honest "I could not check this", where compliance produced a false *HIGH*.

So what looked like one problem was two with different severities, and the severe one
was already closed by C and A. What remained was worth five lines of normalising and an
alternates list reusing the compliance shape — not a new authoring surface. See
`docs/phase-6.16.md` §6.16d.

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

## C, as built · ✅ complete

`checks/compliance_match.py`. Four tests, and a block counts if **any** of them passes,
so nothing that matched before stops matching:

1. **Normalised substring** — what the old check did, with case, underscores and hyphens
   treated as noise.
2. **Segments in order** — the rule's segments as an ordered subsequence of the path's.
3. **Keys inside the block** — the parser groups a nested object into one block, so
   `{"suppressions": {"lists": {"ofac": true}}}` is the single path `suppressions.lists`
   holding `{"ofac": true}`. The control is real and it is in the *content*.
4. **Alternates** — other paths that also count, written by a person.

Re-running the measurement against it:

| Configuration shape | Before | After | With an alternate |
| --- | --- | --- | --- |
| Exactly as the rules expect | 0 | 0 | 0 |
| `opt_out` vs `optout` | 1 | **0** | 0 |
| Grouped under `exclusions` | 3 | 3 | **0** |
| Vendor names | 3 | 3 | **0** |
| Nested one deeper | 3 | **0** | 0 |
| Genuinely absent | 2 | 2 | **2 — still correctly reported** |

Two shapes fixed with no configuration at all, two more with one path an administrator
types, and the check still reports a control that genuinely is not there. That last row
is the one that makes the rest safe to ship.

**Two things the build found that the specification had not.**

- **The nesting row was not what it looked like.** `suppressions.lists.ofac` is not a
  path the parser produces — it produces `suppressions.lists` holding an object. So
  segment matching alone did not fix that row; reading the block's *content* did. The
  specification had the symptom right and the mechanism wrong.
- **Segment matching alone would have been a regression.** The old substring test found
  `suppressions.ofac_sdn` for a rule saying `suppressions.ofac`, by luck, and that is
  the right answer. Normalised segments reject it. Keeping the substring test as one of
  the four is what makes the change purely additive.

**The looseness that remains, stated rather than hidden.** The substring test cannot
tell `suppressions.ofac_sdn` — a real control under a vendor name — from
`suppressions.ofacish_thing`, which is not one. Dropping it would fix that and would
also stop finding `ofac_sdn`. Between a rule that occasionally matches too generously
and one that reports a real control as missing at high severity, the generous failure
is the safer one: it is visible on the finding, which names the path it matched.
Narrowing it properly is what option A is for. There is a test that states this
explicitly rather than asserting behaviour the code does not have.

## What to settle before this becomes a build plan

- [ ] Is a model-located match a **finding** or a **confirmation prompt**? Review
      severity plus write-back is the current leaning, because it self-corrects.
- [ ] Does a confirmed location amend the rule **automatically or through the training
      queue**? ADR-021 points at the queue.
- [x] **Run statistics should say which engine answered.** Built in 6.16b:
      `Finding.engine` is `code` or `model`, and a run's statistics count them.
      Original note follows.
- [ ] (superseded) When a rule is decided by
      code and when it is decided after a model call, the run's statistics should
      distinguish them, so the cost and the reliability of each path are visible rather
      than inferred. This is wanted whichever shape is chosen.
- [x] Does the same problem apply to **programme rules and checks**? Named values:
      measured in 6.16d — brittle, but they fail *safe*, at review severity rather
      than high. The programme keyword check is still unmeasured.
- [ ] How does scope interact — global rules, delivery-programme rules, and the
      per-submission context — when the model is asked to locate something?

## Not in scope

**Letting the model decide compliance.** See "The constraint any answer has to satisfy".

**Rewriting the deterministic check.** It is correct where naming matches, and the
measurement says so. Whatever is built goes *behind* it, not instead of it.

## A, as built · ✅ complete

`llm/prompts/compliance_locate.py` and `pipeline/s6_reverse.py`. Asked **only** where the
deterministic matcher has already failed, so the common case still costs nothing and a
configuration whose naming matches never reaches the model at all.

The model is asked *where the control is, if anywhere* — never whether the delivery is
compliant. It is shown configuration paths and the shape of their contents, never a
value (ADR-003). It answers `found`, `absent` or `unsure`.

**Four things code refuses to believe**, each falling back to the finding the old
behaviour would have produced, and each with a test:

| The answer | Why it is discarded |
| --- | --- |
| A path that was not in the list | A hallucinated path must not clear a compliance rule. The prompt says the path will be rejected; code rejects it. |
| Confidence below 0.6 | A locator that is unsure has told us nothing the matcher had not. |
| `unsure`, or anything but `found` | Only a positive location counts. |
| No answer at all | An unavailable model must never turn a miss into a pass. |

**A located control is never a pass.** It becomes a **review-severity** finding naming
the path and asking a person to confirm, with the next step written into the finding:
add the path to the rule as an alternate and the next run matches it in code, without
asking again. That is the write-back the specification wanted, done by a person rather
than silently — ADR-021 — and it means the model is consulted once per customer per
rule rather than on every run.

**What this changed about the stage.** `s6_reverse.py` opened with *"Pure code, no LLM
call"* for its whole life. It now makes one, in one place, and its documentation says
so — as does `docs/model-context.md`, which a test keeps honest: the register lists
which stages build a preamble, and stage 6 joining that list is what made the test fail
until both were corrected.

## The open questions, answered by the build

- **Is a model-located match a finding or a confirmation prompt?** A confirmation
  prompt, at review severity. Not a pass, because deciding compliance is a comparison.
- **Automatic write-back or the training queue?** Neither, in the end: the finding tells
  the person what to add, and they add it. Simpler than a queue round-trip for a
  one-line change, and it keeps ADR-021's rule that nothing activates without a person.
- **Run statistics saying which engine answered.** Still outstanding. A run records its
  calls and cache hits, so the locator's cost is visible in aggregate, but a finding
  does not yet say whether code or the model produced it.
- **Does the same problem apply to programme rules and checks?** Still unmeasured.
  Worth the same half-hour the compliance measurement took.

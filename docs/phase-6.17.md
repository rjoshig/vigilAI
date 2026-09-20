# Phase 6.17 — What is left, gathered in one place

**Status:** 🟡 **in progress** — specified 2026-09-21 as a hand-off; **6.17a is
measured and closed** (2026-09-20), and what it found is written up below. Everything
still open after 6.14, 6.15 and 6.16 is collected here so the next person picks up one
document rather than three, and so nothing survives only as a line in a session log.

Numbered 6.17 rather than 6.18 because it is the next number and the phase docs are
read in sequence; nothing is missing between 6.16 and this.

**None of this is blocking.** The product is built, merged to `main`, and every gate is
green at 1412 tests (1391, plus the 21 that record 6.17a's measurement). These are the
things deliberately left, each with the reason it was left and what would settle it.

## The work, in the order worth doing it

### 6.17a — Measure the programme keyword check · ✅ complete

**Measured 2026-09-20. The answer is that it is brittle, and it fails the way compliance
rules did — at HIGH severity — not the way named values do.** The precedent that
applies is `docs/phase-6.15.md`, not 6.16d.

The measurement is `tests/pipeline/test_programme_keyword_brittleness.py`, run against
the seeded programmes in `DEFAULT_SCOPES` rather than invented ones, because the seeded
words are what a customer meets on their first run.

#### What was measured

Seventeen deliveries, **every one of them genuinely the programme it declares**, worded
the way a different customer might word it. A finding on any of them is a false positive.

| Wording of a delivery that IS the declared programme | Result |
| --- | --- |
| Exactly as the keywords expect (`prescreen`, `firm offer`) | silent — correct |
| Inflected: `prescreened`, `solicitations`, `archives` | silent — substring matching handles English for free |
| Hyphenated: `invitation-to-apply` | review |
| Plain business words: *promotional acquisition campaign* | review |
| The abbreviation the business says out loud: `ITA` | review |
| Phrase halves recombined: `portfolio monitoring` | review |
| Singular where the keyword is plural: `existing account` | review |
| *ongoing review of the portfolio*, *account management refresh* | review |
| *back-file extract*, *legacy history pull* | review |
| A realistic prescreen OSL, **one phrase reworded** | **high** |
| A delivery in plain words that also says `snapshot` and `historical` | **high** |

And the control, which matters as much as the rest:

| A delivery genuinely declared as the wrong programme | Result |
| --- | --- |
| AS declared, the document is plainly AM (and two more like it) | **high** — correct, 3 of 3 |

#### The two defects, stated precisely

**One — a phrase keyword needs exact adjacency and exact plurality.** `existing accounts`
is not a substring of `existing account`; `portfolio review` is not a substring of
*ongoing review of the portfolio*; `invitation to apply` is not a substring of
`invitation-to-apply`. Single-word keywords survive inflection for free, so the shipped
programmes are unequally exposed: Archives, whose words are all single, is robust, and
Account Monitoring, whose words are all phrases, is the most fragile thing here.

**Two — two of the shipped keywords carry no programme meaning.** Severity is `high`
only when another programme clears the two-hit floor. `snapshot` and `historical` are
ordinary data-delivery vocabulary that appears in a specification for *any* programme,
so Archives clears that floor by accident. A delivery whose own words were missed is
therefore not merely raised for review — it is confidently reported as **Archives**, at
the highest severity the tool has, on the strength of two words that say nothing about
which programme anything is.

**The two compound.** Defect one opens the door; defect two walks through it at HIGH.
The knife-edge row is the sharpest, and it is the same shape as 6.15's *one extra level
of nesting*: a realistic prescreen OSL is silent only because its last sentence happens
to say `firm offer`. Reword that one phrase — leaving a document still plainly a
solicitation — and the run is reported as a different programme.

#### Why this reads differently from the named-values answer

6.16d left named values alone because they fail to `could_not_evaluate` at review
severity: an honest *I could not tell*. This check does that **only when no other
programme scores two hits**, and the accidental-keyword defect makes that condition
unreliable precisely when the document is ordinary. It is 6.15's failure mode — absent
and *spelled differently* reported identically, at HIGH — not 6.16d's.

#### What the check gets right, and must keep

The control class passes 3 of 3, and the inflection class is silent for free. **The
check is not broken and should not be replaced.** Where the words match it is exact,
free, reproducible, and explainable — *"none of Account Solicitation's words appear;
two of Archives' do."* Anything built goes behind it, as 6.15's option C did.

- [x] Measure it the way `docs/phase-6.15.md` measured compliance.
- [x] Record the result in this document whichever way it goes.
- [x] Decide whether anything needs building. **It does** — the recommendation is below,
      and it is a decision for the user, not a thing to start.

#### Recommended, not started

Cheapest first, and the first two may be enough:

1. **Fix the seeded keywords, which is a data change, not a code change.** Drop
   `snapshot` and `historical` from Archives, or replace them with words that mean
   Archives (`back-file`, `legacy extract`, `prior-year`). This alone removes most of
   the HIGH escalations, because it stops one programme clearing the floor by accident.
   Add the singular and hyphenated forms the measurement found.
2. **Normalize before matching.** Fold hyphens to spaces and collapse whitespace on both
   sides, and match a phrase on a stemmed word sequence rather than a raw substring.
   That is 6.15's option C applied to this surface, and it closes the plural and
   hyphen rows without any new vocabulary.
3. **Raise the floor for a HIGH, or lower the severity.** A programme should not be
   named as the answer on two generic words. Either the floor rises above two, or
   confidence has to come from words that only that programme uses.
4. **Only if 1–3 leave something:** the 6.15 option A shape — ask the model *which
   programme does this read like*, code decides what that means. The measurement does
   not obviously need it, and it costs a model call on a check that is free today.

### 6.17b — The live cap countdown · ⬜ not started

Deferred twice by the user as a nice-to-have, and still is.

An administrator writing background context sees the cap stated — *"1,500 characters,
and 6,000 across everything that reaches one prompt"* — but not how much is left. The
eleventh configuration note on a configuration is silently trimmed, and the person
writing it finds out afterwards, if at all.

- [ ] The API reports a run's remaining prompt budget, or a configuration's, so a field
      can show what is left rather than the limit.
- [ ] The marker counts down instead of stating a constant.

**Why it has stayed deferred:** the caps are stated honestly and the trimming tells the
model what was left out, so nothing is silently wrong — it is only less helpful than it
could be. Worth doing when somebody hits it, not before.

### 6.17c — How scope interacts with the compliance locator · ⬜ not started

The last unanswered question from `docs/phase-6.15.md`.

A compliance rule carries a scope. The locator is asked about a configuration without
being told which programme the run belongs to, or what the programme's standing
instructions say about it.

- [ ] Decide whether the locator should see the run's programme and its standing
      instructions. The argument for: "OFAC screening" may be implemented differently
      under Account Solicitation than under Archives, and the model cannot know that.
      The argument against: every field added to that prompt is one more thing that can
      steer it toward finding something, and the locator's honest prior is that the
      control is absent.
- [ ] If it should, it belongs in the existing preamble rather than a new prompt field,
      because that is where scope context already reaches every other stage.

**Not urgent:** the locator is already conservative, and code rejects any path it did
not offer.

## Standing touchpoints, which are nobody's phase and everybody's problem

These are in `CLAUDE.md` as recurring obligations. They are listed here because two
phases closed without them and that is how they decay.

- [ ] **`docs/gd-rollout-plan.md` has not been re-read since 6.13.** `CLAUDE.md` says to
      re-read it at every milestone and update the readiness checklist. Three milestones
      have closed since.
- [ ] **The training documents say "after Phase 6.14."** 6.15 and 6.16 have shipped, and
      6.16 changed a screen a user looks at every day — the runs list.

## What is deliberately not here

**Option B from 6.15** — a rule carrying what it looks like in each artifact. Measured
in 6.16d and **should not be built**: what looked like one problem was two with
different severities, and the severe one was closed by 6.15's options C and A. See
`docs/phase-6.15.md` for the reasoning. Reopen it only with a case the measurement does
not already answer.

**Phase 7** stays dormant. It runs only when the user asks, on the machine holding the
real files, and it is not a prerequisite for anything (ADR-019).

## Where things stand, for whoever picks this up

- `main` is at the merge of PR #52. `dev` and `main` agree.
- **1412 tests pass.** `black`, `flake8`, `mypy`, both UI gates and
  `scripts/check_docs.sh` are clean.
- The tool has been run end to end on a real commercial model (Claude Haiku 4.5): a full
  run in 33 seconds for about five cents, reproducing the planted findings exactly.
- **Start with `docs/session-log.md`.** Its "Resume here" block is the entry point, and
  this document is what it points at.

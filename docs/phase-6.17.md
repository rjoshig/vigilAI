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

### 6.17a — Measure the programme keyword check, and repair it · 🟡 in progress

**Measured 2026-09-20, and repaired the same day.** The answer was that it is brittle,
and that it fails the way compliance rules did — at HIGH severity — not the way named
values do. So 6.15's precedent applied, not 6.16d's, and the deterministic repair 6.15
used was the right shape. **False high-severity findings went from five to one**; what
is left is a meaning problem, deferred to [`phase-6.18.md`](phase-6.18.md) 6.18f.

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

#### What was built, and what it cost

Two changes, neither of which asks a model anything. ADR-042 records the decision.

**Match loosely** — `checks/programme_match.py`, in the shape `compliance_match.py`
established. Three tests, any of which finds a keyword: a normalised substring (first,
because it preserves every match the old behaviour made, inflections included), the
keyword's words adjacent after a conservative singular fold, and — for a multi-word
keyword only — its words within a stated window of each other in any order. The fold
removes a plural and nothing else; a stemmer would also fold tense and derivation, and
a false match here has to be explainable to the person reading the finding.

**Count strictly** — a programme may be named as what a delivery "reads like" only on
words **it alone claims**, and only when it is strictly ahead of the next programme. A
tie is not an answer. The shipped lists lost `snapshot` and `historical` and gained the
words the business says: `portfolio monitoring`, `account management`, `promotional
offer`, `acquisition campaign`, `back file`, `prior year`, `legacy extract`.

The structural guard matters more than the keyword edit. Removing two words fixed one
instance; *a programme is named only on words it alone claims* is what stops an
administrator recreating it with the next overlapping word they add.

#### The measurement, re-run

The same twenty deliveries, every one genuinely the programme it declares:

| | Before | After |
| --- | --- | --- |
| Silent — correct | 4 | **15** |
| Review — honest, but noise | 11 | 4 |
| **High — a false positive at the top severity** | **5** | **1** |
| Control: genuinely the wrong programme, caught | 3 of 3 | **3 of 3** |

The four review items left are honest ones: `ITA` for *invitation to apply*, and a
*legacy history pull* where the list says `legacy extract`. No spelling rule turns an
abbreviation into the phrase it stands for, and the tool says it has not found the
programme's words rather than claiming to know what the delivery is instead. An
administrator adding the customer's word closes each one permanently.

#### The one case left, and why it is left

A delivery that calls itself a *promotional acquisition mailing* and says *suppress
existing accounts; an account review removes anyone already on file* has two of Account
Monitoring's words and none of its own, and is still reported at **high**.

**Nothing is misspelled.** The words really are the other programme's, and what makes
them innocent is that they appear under *suppress* and *removes* — a prescreen
excluding the customers it already has. That is meaning, and no normalising rule
reaches it. It is kept as a test, and it is the worked example
[`phase-6.18.md`](phase-6.18.md) 6.18f exists to close: the model asked once, after the
code check has failed, answering *which programme does this read like* and never *is
this correct*, which stays code's (ADR-001).

- [x] Fix the seeded keywords — a data change, and the structural guard behind it.
- [x] Normalize before matching.
- [x] Do not name a programme on words that carry no programme meaning.
- [ ] **Deferred to 6.18f, not dropped:** the model as a second opinion after the code
      check fails. The deterministic repair took the false-high count from five to one,
      so this is now one case rather than a class — and the one case is a meaning
      problem, which is what the model is for.

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

### 6.17c — How scope reaches the compliance locator · ✅ complete

The last unanswered question from `docs/phase-6.15.md`, and the answer is that **it was
already answered by the code**. ADR-044 records it.

The question was written as though the locator is asked about a configuration without
being told which programme the run belongs to. It is not: `_locate()` prepends
`preamble(context.guidance)`, and that preamble emits the programme's label and that
programme's standing instructions, labelled as background. Nobody decided this — it
arrived with the preamble when 6.15 option A was built — and **nothing asserted it**, so
a refactor could have dropped it or doubled it with every test still green.

- [x] Decide whether the locator should see the run's programme and its standing
      instructions. **It already does, and it keeps doing so.** The argument against is
      real and specific — this is the only call whose answer can soften a high-severity
      compliance finding — but it is bounded by guards code already applies: the model
      may only quote a path it was offered, must clear a confidence floor, must answer
      `found` rather than hedge, and a located control is never a pass. At worst a
      standing instruction costs a reviewer one more question.
- [x] It belongs in the existing preamble rather than a new prompt field, which is where
      it already was.
- [x] Four tests now pin what reaches this prompt: that both arrive, that they are
      labelled as background rather than as a requirement, that the preamble is sent
      once rather than twice, and that a run with nothing configured sends no preamble
      at all.

**Left available, not done:** sending the programme label without the administrator's
free text. A one-line change if a measurement ever shows the prose steering an answer,
and measuring it needs a real model because the mock always answers `absent`. Worth
doing if the locator is ever seen to be too generous; not worth blocking on.

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

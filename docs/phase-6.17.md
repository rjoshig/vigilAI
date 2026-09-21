# Phase 6.17 — What is left, gathered in one place

**Status:** ✅ **complete** — 2026-09-21. Specified 2026-09-21 as a hand-off;
**6.17a was measured and closed** (2026-09-20), and what it found is written up below.
6.17b and 6.17c followed, and both standing touchpoints were brought current. Everything
still open after 6.14, 6.15 and 6.16 is collected here so the next person picks up one
document rather than three, and so nothing survives only as a line in a session log.

Numbered 6.17 rather than 6.18 because it is the next number and the phase docs are
read in sequence; nothing is missing between 6.16 and this.

**None of this is blocking.** The product is built, merged to `main`, and every gate is
green at 1412 tests (1391, plus the 21 that record 6.17a's measurement). These are the
things deliberately left, each with the reason it was left and what would settle it.

## The work, in the order worth doing it

### 6.17a — Measure the programme keyword check, and repair it · ✅ complete

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
- [x] **Done in 6.18f**, the same day. The deterministic repair took the false-high
      count from five to one, and the one left was a meaning problem rather than a
      spelling one — so the model reads the delivery once, after the code check has
      failed, and code decides what its answer means (ADR-045). The case that started
      this now drops from high severity to a question, and the customer's own words are
      offered to an administrator so the question stops recurring.

### 6.17b — The live cap countdown · ✅ complete

Built 2026-09-20, after being deferred twice as a nice-to-have. It was cheap once the
preamble was split so the number could be measured from the text a prompt actually
carries rather than from a second implementation that would drift from it.

- [x] `GET /admin/prompt-budget` reports what a programme's and a configuration's
      context already spends of the 6,000, and what is left. Counted over the lines
      `preamble` renders, by the same function that renders them, and the way the
      trimmer counts them — so the number shown is the number that decides what gets
      dropped.
- [x] `<CapMeter>` on the standing-instructions and AI-context fields counts **down**:
      *"1,240 characters left in this field · 4,760 left across everything in this
      prompt"*, and says plainly when the block is already over and losing its oldest
      lines. The artifact field's note no longer recites the two constants.

**What it does not do:** count a configuration's notes live as somebody types a
*different* configuration's note, because the two are written on different screens. The
number is exact for what is saved and an estimate for what is being typed, which is the
honest way round.

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

These are in `CLAUDE.md` as recurring obligations. They were listed here because two
phases closed without them and that is how they decay.

- [x] **`docs/gd-rollout-plan.md` re-read** (2026-09-20, dated in the document). Stage 1
      gained two readiness items the recent phases created — matching each programme's
      keywords to the customer's vocabulary against the two rules 6.17a established, and
      a decision on the compliance locator's model call — and a line saying the Review
      load screen is understood before stage 3 and left alone until then. Stage 3 gained
      the item that matters most: **its gate now requires the Review load question to be
      answered in writing**, because that stage is the first time the tool has real
      verdicts and [`phase-7.1.md`](phase-7.1.md) is how they are read.
- [x] **The training documents re-aligned** and re-dated. `admin-training.md` gained the
      keyword rules, the Review load screen, and the AI's second reading of a delivery's
      programme; `user-training.md` gained what a reviewer now sees when the tool is
      unsure which programme a delivery is.

## What is left

Nothing in this phase. What remains in the product is in
[`phase-6.18.md`](phase-6.18.md) b–e, which wait on real verdicts
([`phase-7.1.md`](phase-7.1.md)), and the standing items that need the user or the
target machine, listed in [`session-log.md`](session-log.md).

# Phase 6.17 — What is left, gathered in one place

**Status:** ⬜ **not started** — specified 2026-09-21 as a hand-off. Everything still
open after 6.14, 6.15 and 6.16 is collected here so the next person picks up one
document rather than three, and so nothing survives only as a line in a session log.

Numbered 6.17 rather than 6.18 because it is the next number and the phase docs are
read in sequence; nothing is missing between 6.16 and this.

**None of this is blocking.** The product is built, merged to `main`, and every gate is
green at 1391 tests. These are the things deliberately left, each with the reason it was
left and what would settle it.

## The work, in the order worth doing it

### 6.17a — Measure the programme keyword check · ⬜ not started

The one genuinely unfinished piece of investigation. Two surfaces have been measured for
the same defect and answered differently:

| Surface | Brittle? | What happens when it fails |
| --- | --- | --- |
| Compliance rules (6.15) | Yes | A false finding at **HIGH** severity — fixed |
| Named values (6.16d) | Yes | `could_not_evaluate` at **review** — honest, left alone |
| **Programme keywords** | **Unmeasured** | **Unknown** |

The programme check greps a delivery's inputs for a programme's words and reports
`programme_mismatch` when it finds fewer than two. The question is the same one asked
twice already: what happens when a customer's documents use different words for the same
programme.

- [ ] Measure it the way `docs/phase-6.15.md` measured compliance: take the seeded
      programmes, run them against inputs that describe the same programme in other
      words, and count what fires.
- [ ] Record the result in this document whichever way it goes. **A measurement that
      says "this is fine" is worth as much as one that says it is not** — it retires the
      question instead of leaving it to be re-asked.
- [ ] Only then decide whether anything needs building. The two precedents point
      opposite ways, so the answer is not guessable from them.

**Roughly half an hour**, and it either creates a phase or removes a worry.

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
- **1391 tests pass.** `black`, `flake8`, `mypy`, both UI gates and
  `scripts/check_docs.sh` are clean.
- The tool has been run end to end on a real commercial model (Claude Haiku 4.5): a full
  run in 33 seconds for about five cents, reproducing the planted findings exactly.
- **Start with `docs/session-log.md`.** Its "Resume here" block is the entry point, and
  this document is what it points at.

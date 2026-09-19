# Phase 6.7 — Programme rules and the programme check

**Status:** ✅ **complete** (2026-09-19). Built the day it was asked for. See
"Decisions" for what the user chose.

**Goal:** two things a delivery programme did not have. Rules of its own, several per
programme, each with a strictness the tool turns into a severity. And a first check
that a run declared as one programme actually reads like that programme in its own
inputs.

## The idea

A programme rule is a sentence an administrator writes: *every prescreen delivery
excludes accounts that opted out of firm offers.* The model reads each delivery
against the programme's rules and names what it breaks, quoting the evidence. **The
model never grades.** The rule's strictness, must, should, or advisory, is what
decides how serious a breach is, and code applies it: high, medium, low. That keeps
the one design rule, the model judges meaning and code decides everything else
(ADR-001), while letting an administrator say how much a rule matters.

The programme check is a grep, and it says so. Each programme carries words that
mark a delivery as its own. The check scans the OSL, the configuration, and the
report headers; a run declared as Account Solicitation whose inputs carry none of
its words and plenty of Account Monitoring's gets a high finding before anything
else is checked, naming what it looked for and what it found instead. Deliberately
simple so it is deliberately explainable.

## Scope · ✅ complete

**Programme rules** · ✅ complete
- [x] `programme_rules`: programme, title, text, strictness (must · should ·
      advisory), sort order, and the same lifecycle every rule has (ADR-021): draft,
      shadow, active, disabled, deleted.
- [x] Admin console: several rules per programme on the Delivery programmes screen,
      each with its strictness; enable, disable, delete and restore through the
      Rules screen, where programme rules appear as a fourth kind.
- [x] Stage 8 reads the delivery against the programme's rules in one call: the
      extracted requirements, the configuration description, and one-line report
      summaries, never a row. Each breach becomes a `programme_rule_violation`
      finding whose severity comes from the rule's strictness. A rule id the prompt
      never listed is ignored as invention; a breach under 50% confidence is a
      review item rather than a graded finding.
- [x] Shadow works for programme rules as for any other.

**The programme check** · ✅ complete
- [x] `run_scopes.keywords`, seeded: Account Solicitation (prescreen, firm offer,
      invitation to apply, …), Account Monitoring, Archives. Editable on the
      Delivery programmes screen.
- [x] Stage 7 scans the OSL text, the configuration blocks, and every report's
      sheet names and headers. Declared programme's words present: nothing.
      Absent, and two or more of another programme's present: a high
      `programme_mismatch` finding naming both. Absent with no other signal: a
      review item.

**Documentation and tests** · ✅ complete
- [x] ADR-026; glossary; the training documents; the prompt registered and covered
      by the prompt suite (no compute, JSON only, worked examples that validate).
- [x] Tests: several rules per programme with their own strictness; the Rules
      screen and lifecycle; keywords seeded and editable; the three outcomes of the
      check; and end to end, a scripted model naming two breaches and an invented
      rule id, with the findings carrying high and low from the rules and nothing
      from the invention.

## Acceptance criteria · ✅ complete

1. [x] An administrator adds three rules to a programme with three strictnesses.
2. [x] A run in that programme produces findings whose severities are the rules'.
3. [x] A run declared as one programme whose inputs read like another gets a high
   finding that says what it looked for and what it found.
4. [x] Every existing test still passes: 886.

## Decisions (2026-09-19)

| Question | Decision |
| --- | --- |
| Strictness scale | **must / should / advisory**, mapping to high / medium / low. |
| Who judges a breach | **The model reads; code sets the severity.** |
| A programme mismatch | **A high finding, and the run continues.** Nothing is blocked on a keyword check. |
| Where the words come from | **Admin-editable keywords per programme**, shipped with defaults. |

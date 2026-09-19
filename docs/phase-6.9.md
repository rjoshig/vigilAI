# Phase 6.9 — Delivery drift

**Status:** ✅ **complete** (2026-09-19). Answers the design doc's open question
"comparison against the same customer's previous run".

**Goal:** a reviewer's first question on a repeat delivery is *what is different from
last time*. The tool now answers it from what is already stored, in code, with no
model call (ADR-030).

## The idea

Every run of a configuration id leaves behind its findings with their decisions, its
extracted requirements, and the configuration it carried. Given the previous
**finalized** run of the same configuration for the same customer, four comparisons
fall out:

- **Findings** that are new and findings that went away, matched on type, leg and
  title, which code generates and therefore keeps stable across runs.
- **Not OK items carried over**: findings the previous reviewer marked Not OK that
  are back in this delivery. This is the one worth a warning, and it is shown first.
- **Requirements** whose extracted value changed (or appeared, or vanished), matched
  on type and OSL reference rather than on `R-nnn`, which is renumbered on every
  extraction.
- **The configuration**, as a diff by JSON path, ignoring `last_modified`.

Shadow findings are left out on both sides: they were shown to nobody (ADR-021).

## Scope · ✅ complete

- [x] `db/drift.py`: the previous finalized run, the four comparisons as pure
      functions, and `compute_drift` over stored rows.
- [x] `GET /runs/{id}/drift` (`DriftOut`); a `reason` when there is no earlier run.
- [x] Review screen: a **Since the previous run** card above the findings, with the
      carried Not OK items first, new and resolved findings, and collapsible lists of
      changed requirements and configuration paths.
- [x] Frozen report: a **Since the previous run** section before the detail, computed
      at finalize and frozen with the rest.
- [x] Tests: the pure comparisons; two runs of one configuration, the second with one
      new finding and one resolved; a Not OK item carried over; the section on the
      frozen report and absent from the first run's report.
- [x] ADR-030, glossary, training document, the design-doc question ticked.

## Acceptance criteria · ✅ complete

1. [x] Two runs of one configuration, the second with one new finding and one
   resolved: the panel and the report show exactly those.
2. [x] A run with no configuration id, or the first run of one, says why there is no
   comparison rather than showing an empty panel.
3. [x] Nothing here calls the model; the run's LLM call count is unchanged.

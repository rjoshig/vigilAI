# Phase 6.8 — Scoped compliance, validation guides, and versioned definitions

**Status:** 🟡 **in progress** — decided 2026-09-19; 6.8a landed 2026-09-19.

**Goal:** three things an administrator cannot express today, and a safety net for
the definitions they edit.

1. **Compliance rules per programme.** A compliance rule applies everywhere or to one
   customer; it cannot apply to Account Solicitation and not to Account Monitoring.
2. **Validation guides.** A way to tell the model, per report type, *what to look at,
   what a cell means, where it comes from in the OSL and the configuration, and what
   to check it against*, with two or three worked examples. Today an artifact type
   has one paragraph of guidance and up to three sample workbooks; there is no
   structured way to say "this cell is the billing count, it answers OSL section 6,
   the config sets it at `waterfall.steps[3].count`".
3. **Versioned definitions with revert.** Every edit to an artifact type, its samples,
   its guides, and programme rules keeps the last ten versions, and an administrator
   can put any of them back.

## What exists, and what changes

| Today | After |
| --- | --- |
| `compliance_rules.scope` is `all` or a customer name (`checks/definitions.py:71`); stage 6 filters on it. | Scope also accepts `programme:CODE`. Stage 6 applies global rules plus the run's programme's rules; another programme's never. The compliance screen gains a scope picker: everywhere, one programme, one customer. Same for checks, which have the same scope column. |
| An artifact type has `ai_context` (one paragraph) and up to three samples; named values point at cells for code checks. | A **validation guide** per artifact type: an ordered list of entries, each *what it is* (a cell, a label lookup, or a whole sheet), *what it means*, *where in the OSL* (section or phrase), *where in the configuration* (JSON path), *what to validate* (plain words), and up to three examples drawn from the samples (the cell's value in each sample). The guide is shown to the model in stage 4 (trace) and stage 8 (programme reading) as structured context, and any entry that names a cell and a config path is also compiled into a **check** the code runs, so the guide is both explanation and enforcement wherever it is concrete enough. |
| No versioning on artifact types, samples, guides, or programme rules. Configs captured per run are versioned already and stay. | A `definition_versions` table: on every save of an artifact type (with its samples and guide) or a programme's rules, the previous state is snapshotted as JSON with who and when. The last ten are kept per object. A **Versions** control on the card lists them; **Revert** restores one, which itself creates a new version so nothing is lost. |

**In the absence of a guide the model works exactly as it does now.** A guide is
additive context and additive checks, never a precondition (ADR-020's rule, kept).

## Scope · 🟡 in progress

### 6.8a — Compliance and checks scoped to a programme · ✅ complete

- [x] `scope` on `compliance_rules` and `check_definitions` accepts `programme:CODE`;
      `applies_to` in `checks/definitions.py` and the stage 6 filter honour it,
      alongside `all` and a customer name.
- [x] the pipeline reads the run's programme code from its guidance and keeps only
      rules in scope, so a rule for Account Solicitation is never evaluated on Archives.
- [x] Compliance screen and Checks screen: a scope picker (everywhere / programme /
      customer) on create and edit; the list shows the scope.
- [x] The Rules screen renders `programme:CODE` as the programme's name (done for
      programme rules already).

### 6.8b — Validation guides · ⬜ not started

- [ ] `validation_guides`: `artifact_type_id`, ordered `entries` (JSON), `version`,
      `updated_by`, `updated_at`. An entry: `{locator: {kind: cell|label|sheet,
      sheet, cell|label, column}, meaning, osl_ref, config_path, validate, examples:
      [{sample_id, value}]}`.
- [ ] Admin console, on the artifact type card: a **Guide** editor. Pick a cell or
      label from the sample preview (the preview already lists cells with their
      labels), write what it means, point at the OSL and the configuration in words
      or paths, say what to validate. The examples fill themselves from the stored
      samples when the locator resolves on them.
- [ ] Guidance to the model: entries reach stage 4 and stage 8 as a structured block
      per report type, labelled as background (the model reads meaning, code
      compares). Kept short: entries only, no values beyond the examples.
- [ ] Compilation to checks: an entry with a resolvable locator **and** a config path
      becomes a named value plus a check ("report cell equals config value" or
      "reconciles within tolerance", chosen in the entry), created in **shadow** with
      origin `guide`, so an administrator sees it fire before it counts. Entries
      without a config path stay explanation only.
- [ ] The frozen report notes which guide version was in force.

### 6.8c — Versioned definitions with revert · ⬜ not started

- [ ] `definition_versions`: `kind` (artifact_type | programme_rules), `object_id`,
      `version`, `snapshot` (JSON), `created_by`, `created_at`. Written on every save
      of an artifact type (fields, sample list, guide) and on every change to a
      programme's rule set. **Keep the last ten** per object; older ones are purged
      by the retention sweep.
- [ ] Sample files referenced by an old version are kept on disk while any retained
      version references them, so a revert brings the workbooks back too.
- [ ] Admin console: a **Versions** control on each artifact type and programme card
      listing the ten with who and when and a one-line diff summary; **Revert**
      restores the snapshot as a new version, with the typed word, and is audited.
- [ ] Runs record the artifact-type version they were parsed under, so a finding on
      an old run still points at the definition that produced it.

### 6.8d — Documentation and tests · 🟡 in progress

- [x] ADR-029 (scope tokens; guides are additive; versions are snapshots, revert is a new version).
- [ ] Training documents, glossary, and this phase closed out.
- [ ] Tests: a programme-scoped compliance rule fires on its programme and not on
      another; a guide entry with a config path compiles into a shadow check that
      fires; a guide without one changes only the prompt; ten versions kept and the
      eleventh purged; revert restores samples and guide together.

## Acceptance criteria · 🟡 in progress

1. [x] A compliance rule scoped to Account Solicitation produces a finding on an
   Account Solicitation run and none on an Account Monitoring run; a global rule
   fires on both.
2. [ ] An administrator writes a guide entry pointing a report cell at an OSL section
   and a config path, with examples filled from the samples; the next run shows the
   model was given it and a shadow check exists for it.
3. [ ] With no guide, a run's prompts and findings are unchanged from today.
4. [ ] After eleven edits to an artifact type, ten versions are listed; reverting to
   the third restores its fields, samples, and guide, and appears as version twelve.

## Decisions (2026-09-19)

Answered by the user.

| Question | Decision |
| --- | --- |
| A guide entry with a cell and a config path | **Becomes a check automatically, born in shadow.** Activated from the Rules screen when the numbers say so. |
| Pointing a guide at the OSL | **Both a section reference and a phrase, either optional.** |
| What keeps ten versions with revert | **Artifact types with their samples and guides, and programme rules.** |
| Retention of versions | **Ten in the list, plus any version a run inside the retention window still references.** |

# Phase 6.13 — The loop closes

**Status:** 🟡 **in progress** — specified 2026-09-20, from a second review of the whole
flow: upload to frozen report, the learning loop, and every Train AI surface in the user
app. The review traced the code rather than the documents and then verified each sharp
claim line by line.

**What it found.** The flow is sound where it matters: nothing in the live path asks the
model to compare or compute, reference material reaches the model as labelled background
that is part of the cache key, and learned rules enter the same three tables the engine
already runs and start in shadow. But the loop is not closed, and several of its promises
are silently false. Fifteen defects, none caught by a test or visible on a screen. On the
user side, the author of an observation never learns what became of it, nothing marks a
finding as coming from a learned rule, and the three places where a reviewer actually
forms an opinion — the evidence drawer, the matrix, the coverage gap — have no way to
record it. And every worked example the model sees is hard-coded in Python: an
administrator can teach background prose and the guide and meaning maps, but cannot give
the model a single "this wording → this requirement" pair.

**Decisions taken with the user before this was written:** observations are written by
senior associates, not every reviewer; worked examples come from an admin-curated library
*and* from promotion of confirmed decisions; judgment checks are finished, not removed;
the order is repairs → the reviewer's loop → examples and replay.

Effort 3–4 weeks. Read ADR-001 (code compares), ADR-021 (the model proposes, a person
approves, shadow before it counts), ADR-035 (the fail-closed gate) and
`docs/phase-6.12.md` "Found on the way" first.

## The defects, as found

Each of these is fixed in 6.13a with a test that fails on `dev` today.

| # | Defect | Where |
| --- | --- | --- |
| D1 | The worker drops the lens settings: `resolved_llm_settings` builds `LLMSettings` without `verify_lenses` or `max_lens_calls_per_run`, and no console key exists. Whenever the database is reachable, `LLM_VERIFY_LENSES` in `.env` is ignored and lenses are pinned to `single`. All of 6.11e is unreachable in a deployment | `llm/settings.py` |
| D2 | Several files uploaded for one report kind overwrite each other on disk: `store_upload` writes `runs/<id>/<kind><suffix>` with no part number. Three labelled parts give three rows and one file | `api/uploads.py` |
| D3 | A learned compliance rule can never match: `approve()` writes the candidate's *name* as the config path fragment | `training/synthesis.py` |
| D4 | Shadow compliance rules never run: `ComplianceRule.applies_to` requires `is_active`, unlike `CheckDefinition`, which was fixed for shadow in 6.8 | `checks/definitions.py` |
| D5 | Compliance findings carry no `rule_ref` or `shadow`, so no compliance rule has statistics | `pipeline/s6_reverse.py` |
| D6 | Shadow programme rules produce visible findings: `shadow_rule_refs` holds only field constraints and checks | `db/repository.py`, `pipeline/s8_verify.py` |
| D7 | The programme read never sees requirement text: `getattr(rule.source, "text", "")` on a string literal | `pipeline/s8_verify.py` |
| D8 | AI context written on a report type never reaches a prompt: `preamble` is only ever called for the OSL, the config, or nothing | every `preamble(` call site |
| D9 | Judgment checks are definable, stored, scoped, and skipped with a log line | `pipeline/s7_reports.py` |
| D10 | A candidate with conflicts cannot be approved from the console: `resolution` is required by the API and absent from the admin app, and `find_conflicts` returns no `name`, so the refusal reads "overlaps 2 rule(s) ()" | `admin-ui/app/training/page.tsx`, `training/synthesis.py` |
| D11 | Replay does not replay: a title-substring count, empty for checks and compliance rules; the golden-set replay the docstrings promise does not exist | `api/routers/training.py` |
| D12 | Pressing Save twice creates two observations, and the "say the existing rule is wrong" panel has no control | `user-ui/components/observation-dialog.tsx` |
| D13 | Configuration notes appear in My observations as "Waiting for an administrator", contradicting the note form which says they already reach the model | `api/routers/training.py`, `user-ui/app/observations/page.tsx` |
| D14 | A compliance rule's `expected_value` is never evaluated; a flag set to `false` passes | `pipeline/s6_reverse.py` |
| D15 | Every observation in a batch is linked to one candidate and every candidate to all observations, so "which sentence produced this rule" is unanswerable | `training/synthesis.py` |

Smaller: `last_fired_at` is the last *review*, not the last firing; observation statuses
`queued` and `superseded` are never written; conflicts are computed at synthesis and not
refreshed at approval; an unparseable credit date silently disables its check;
`checks/runner.py` is named in a docstring and does not exist.

## Scope · 🟡 in progress

### 6.13a — Repairs · ✅ complete

- [x] **D1.** `llm.verify_lenses` and `llm.max_lens_calls_per_run` are settings in
      `config/registry.py` with their `.env` names; `resolved_llm_settings` passes both;
      the existing `lenses()` validator applies. A worker context built from the
      environment, and one built from a console override, carries them.
- [x] **D2.** `store_upload` takes the part and writes `<kind><suffix>` for part one (so
      every existing storage key stays valid) and `<kind>-<part><suffix>` beyond. The
      parts test uses distinct bytes per part and asserts distinct storage keys and
      distinct hashes on disk.
- [x] **D3 + D15.** `SynthesizedRule` gains `json_path_contains` and `from_statements`
      (one-based indexes into the statements block); `validate_rule` requires a path for
      a compliance rule; `approve` writes it; `synthesize` links each candidate to the
      observations whose statements produced it, falling back to the whole batch only
      when the model said nothing. Synthesis prompt version bumped; the scripted stand-in
      and the mock answer follow.
- [x] **D4 · D5 · D6 · D14.** `ComplianceRule` carries `id` and `state`; `applies_to`
      mirrors `CheckDefinition`; compliance findings carry `rule_ref` and `shadow`; when
      the path is found, code compares the block's value with `expected_value`;
      `shadow_rule_refs` covers compliance and programme rules. Statistics then work for
      all four rule kinds, and `last_fired_at` comes from the run's date.
- [x] **D7.** The programme read receives `rule.source_text`.
- [x] **D8.** Lens and verify calls pass the report kind from the finding's evidence to
      `preamble`, so AI context written on a report type reaches the model where that
      report is discussed. The console's AI-context field says which stages read it, per
      artifact kind.
- [x] **D10.** `find_conflicts` returns `name` and runs again inside `approve`; the admin
      app sends `resolution`, offering *Replace the older rule* / *Keep both* when a
      candidate has conflicts.
- [x] **D12 · D13.** After a successful save the dialog edits the row it just created, so
      a second Save is an update; *Say the existing rule is wrong* opens a correction
      anchored to the covering rule (new anchor kind `rule`). *My observations* excludes
      configuration notes unless asked for them by kind.
- [x] **Smaller.** A bad credit date is refused at submit with a 422; `queued` and
      `superseded` leave the model docstring and the UI copy; the `checks/runner.py`
      reference is corrected.

### 6.13b — The reviewer's loop closes · ✅ complete

The audience is senior associates. The form gets faster, not wordier.

- [x] **A status chain on an observation**: `waiting → drafted → approved (shadow) →
      live`, or `disabled`, or `rejected` with the administrator's reason. The outcome is
      **derived from the rule tables at read time**, not written at approval: a status
      written then would say "approved" forever while the rule went live or was switched
      off. The wire carries `outcome`, `outcome_note`, `rule_ref`, `rule_name`,
      `rule_summary` and `rule_state`, and *My observations* shows the chain and the
      rule, using the form's own labels rather than raw enums.
- [x] **Provenance on a finding**: `origin` (built-in · admin · guide · meaning · learned)
      and `rule_summary`, resolved from `rule_ref` by one helper. The card carries a
      *Learned from an observation* mark; the evidence drawer shows origin and summary.
- [x] **Rules applied to this run**: a disclosure on the review screen listing the rules
      that produced findings, grouped by origin, with shadow rules named as *running
      silently* and nothing more. `GET /runs/{id}/rules`.
- [x] **Shadow findings visible to administrators only** (ADR-040): the Rules screen
      shows a rule's recent shadow findings with a *Not a real problem* control that
      records a dismissal. That is what makes precision knowable in shadow.
- [x] **The button goes where the opinion forms**: the evidence drawer header, every
      matrix row (anchored to the requirement), and every coverage gap beside *I have
      seen this* (anchored to the requirement and its OSL reference). The run-level button
      gets a real `run` anchor kind.
- [x] **The form**: statement first and focused, expectation second, the three selects
      collapsed under *Details* with today's defaults; one severity vocabulary; the
      personal-data line under the first field; anchors as removable chips; Escape,
      backdrop and focus behave like the configuration viewer; a disabled Save says why.
- [x] Bulk OK reports its count and its errors; the run-page banner reads the gate's own
      reason, so the gate is stated once.
- [x] Browser test: record from a finding and from the drawer; see it on My observations;
      a duplicate Save is an update; the rules applied to a run are listed. The
      coverage-gap path is written and **skips against the demo seed**, which has no run
      with a gap — see "Found on the way".

### 6.13c — Judgment checks, finished under ADR-001 · ✅ complete

- [x] `CheckDefinitionRow` gains `value_names` (a list; migration). The console's
      judgment form asks *Which named values may the model see?*
- [x] Stage 7 resolves only those values, renders `name = value` lines, and calls the
      registered `JUDGMENT_PROMPT`, cached like every call. `fail` → a `judgment_failed`
      finding at the check's severity; `review` or low confidence → severity review;
      `pass` → nothing; an unresolved value → `could_not_evaluate` as today. Counts toward
      the token budget; coverage records the reports the values came from.
- [x] The console keeps *use sparingly* and states the per-run call.

### 6.13d — Controlled examples for the model · ⬜ not started

- [ ] A `prompt_examples` table: stage (a closed set), scope token, `given` (the stage's
      placeholders), `answer` (**validated against the stage's schema on save**, the same
      check the prompt suite applies to the built-ins), note, origin (`admin` or
      `promoted:<kind>:<id>`), active flag, order, author. Versioned like every other
      definition.
- [ ] `Prompt.render_with_examples` appends the active examples for the stage, most
      specific scope first, at most four, in the built-in `Example N … Answer:` shape,
      under one line saying they show the shape of a good answer and are not rules. The
      text is part of the rendered prompt, so the cache key changes on its own. The
      personal-data tripwire runs on save.
- [ ] **Promotion**: one *Use as example* control on a confirmed meaning entry (tracing),
      on a reviewer's requirement edit (extraction), and on an approved candidate
      (synthesis). Each creates a row with its origin; nothing is promoted without the
      click.
- [ ] Admin console **Examples** screen: per stage, the built-ins read-only above the
      library; add, edit, deactivate; a promoted badge; the existing scope control.
- [ ] Tests: every stored example validates; a failing one is refused with the field
      named; rendering respects scope and the cap; a promoted example round-trips.

### 6.13e — A replay that replays · ⬜ not started

- [ ] Replay becomes a worker job: for the last `training.replay_runs` finalized runs,
      re-parse the stored report parts and the captured configuration and evaluate the
      candidate for real with the evaluators that already exist. Result: which runs it
      would have fired on, example titles, and how many of those a reviewer dismissed,
      labelled approximate where it is. "Runs examined" means examined.
- [ ] `validate_rule` parses a drafted check with `expressions.validate`, so a malformed
      expression is refused at draft time rather than becoming a run-time finding.
- [ ] The golden-set claim leaves the candidate model, the wire model and the setting's
      help text.

### 6.13f — Documentation · 🟡 in progress

- [~] ADR-038 (examples are worked examples, never rules; promotion needs a click; a
      per-stage cap; part of the cache key) lands with 6.13d. **Done in 6.13c:** ADR-039
      (judgment checks under ADR-001), ADR-040 (shadow findings visible to administrators
      only, dismissible), and ADR-021's item 6 amended to say how precision becomes
      knowable in shadow.
- [ ] `design.md`, `architecture.md`, `glossary.md`, `llm-privacy.md`, both training
      documents (the Train AI section rewritten for senior associates and the status
      chain), `gd-rollout-plan.md` stage 3.

## Acceptance criteria · 🟡 in progress

1. [ ] `LLM_VERIFY_LENSES=delivery,compliance` in the environment, with the database
   reachable, produces a run whose findings carry those two lens opinions.
2. [ ] Two files uploaded for one report kind with different contents are two files on
   disk, and a finding names the part it came from.
3. [ ] A learned compliance rule approved into shadow produces a hidden finding with a
   `rule_ref` on a configuration that lacks its path, and none on one that has it.
4. [ ] A senior associate records an observation from a coverage gap, an administrator
   approves it, and the author's page says *approved*, names the rule, and later says
   *live*.
5. [ ] A finding produced by a learned rule is marked as such on the review screen.
6. [ ] An administrator adds a worked example for extraction; the next run's extraction
   prompt contains it and its cache key differs; an example whose answer fails the schema
   is refused.
7. [x] A judgment check with two named values produces a finding when the model says
   fail, a review item when it says review, and nothing when it says pass; code sets the
   severity.
8. [ ] Replay of a field-constraint candidate reports the runs it would have fired on,
   computed by evaluating it.
9. [ ] Every existing test still passes; the golden set is unchanged.

## Found on the way

- **The demo seed has no run with a coverage gap.** Every seeded run checks all seven
  requirements, so the browser test for "record from a coverage gap" skips with that
  reason rather than pretending. The API path is covered by unit tests; giving the
  seeder a run whose requirement no report evidences is a small change that belongs
  with the next seeder edit.
- **The observation's outcome is derived, not stored.** The plan said approval would
  write `approved` and activation would write `live`. Reading the rule's own state at
  request time is strictly better: it cannot go stale, needs no hook in the lifecycle,
  and survives a rule being narrowed or disabled after the fact.

## Deliberately not in this phase

- **Showing shadow findings to reviewers.** They carry the review load already; shadow
  precision is the administrator's question, and the administrator is the one who
  activates.
- **Replacing the built-in examples.** The library adds under them; the floor stays.
- **Automatic promotion.** A confirmed decision becomes an example only when a person
  says so. The failure mode of the alternative is a prompt that quietly fills with
  whatever happened to get approved.

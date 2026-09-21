# Phase 6.22 — Product codes, the record layout, and attribute resolution

**Status:** 🟡 **in progress** — 6.22a complete 2026-09-21. The remaining parts are
specified below and not started.

## The goal, in the user's words

> There is a way for text in OSL docx to be mapped to DIRT or other reports, so we can
> have a central location of mappings and anytime the program looks for rows/cell or
> column for that field it can lookup the reference and try and resolve it and use it to
> do the QC.

and

> MODEL in terms of OSL means it's a product code, so we can have product_code=ABC which
> has multiple attributes in it. The OSL may list product code level or on attribute
> level. We want to match the layout in the output and DIRT report against that.

## A question this project has carried since Phase 0

[`design.md`](design.md) already names the mitigation — *"Field names differ across OSL,
config, and reports → Attribute alias table, seeded from a data dictionary if one
exists"* — and carries the matching open question, still unticked: *"Is there an
attribute data dictionary to seed the alias table?"* The same question sits in
[`phase-plan.md`](phase-plan.md), in [`session-log.md`](session-log.md) under
"Outstanding, needs the user", and as an explicit `[~]` partly-met criterion in
[`phase-6.md`](phase-6.md). This phase is the user answering it.

## Where it stops, precisely

Trace `AT01` in the OSL against a DIRT column named `debsc_burs_atyrt_at01_1`:

1. `pipeline/s2_extract.py` puts the OSL string into `rule.values` verbatim.
2. `rules/derive.py` makes `DerivedCheck(kind="fields_present", values=("AT01", …))`.
3. `checks/reports.py` resolves the **structural** names fine through the ladder, so
   `stats` fills with `{"debsc_burs_atyrt_at01_1": …}` and `checks/profile.py` logs
   `profiled 10 attributes from the DIRT`. Everything looks healthy.
4. `resolve("AT01")` normalises to `"at01"`, no alias row exists, and
   `"at01" not in stats` is **True**.
5. Stage 7 publishes `report_violates_rule` at **high**: *"The reports are missing 1
   requested attribute(s): AT01."*

**The tool asserts as fact, at the top of the severity scale, that a delivery is missing
an attribute it in fact delivered.** Three things made it worse than a plain miss:

- It was a **false positive, not a "could not evaluate"**. `stats` is non-empty, so the
  check never degraded. The *same* miss on a bound check returned `passed=None` →
  `could_not_evaluate` at `review`. Two paths, one question, two answers.
- **Nothing recorded it**, so it recurred forever. The suggest-then-accept loop built for
  exactly this (ADR-054, Phase 6.21b) is driven by `LayoutResolver`, never consulted for
  attribute names.
- **The matcher could not span the distance.** `rules/normalize.py` collapses
  `[\s\-_]+`; `at01` and `debsc_burs_atyrt_at01_1` differ by embedded tokens.

And it had **zero test coverage**: every fixture spelled attributes identically in the
OSL and the DIRT, and the one case that renames anything renames *structural* names.

## The vocabulary rule — two collisions, settled the same way

6.21b already owns "layout", and the codebase uses "model" for the LLM everywhere
(`engine="model"`, `LLM_MODEL`, `model_used`). Nothing is renamed; the concepts are
separated by identifier and by word.

| Concept | Code identifier | Words in console and docs |
| --- | --- | --- |
| 6.21b's sheet/column/label spellings | `layout_*`, unchanged | **spelling map** |
| The delivered file's schema | `record_layout` — never bare `layout` | **record layout** |
| A code containing many attributes | `product_code` — never `model` | **product code** |
| The cross-artifact name table | `attribute_terms` / `attribute_spellings` | **attribute dictionary** |

## Scope · 🟡 in progress

### 6.22a — The honest answer · ✅ complete

**Built 2026-09-21**, ADR-059. Ships and releases alone, because it repairs a wrong
answer that was in front of reviewers today and depends on nothing else here.

Two states that shared a code path are told apart by evidence in one place,
`resolve/attributes.py`: **missing** (nothing in the artifact resembles the name —
still a high-severity violation) and **unresolved** (the ladder failed but candidates
resemble it — `review`, naming the closest).

**Found while building.** The near-miss test needs *two* rules, not one. A substring
test alone cannot reach `ST` inside `debsc_burs_atyrt_st_1` — two characters are too
few to be evidence — so a whole-word test carries short names. And a substring test
without a length floor finds `st` inside `incomeest`, which would have softened a
genuinely undelivered attribute into a review record: a false positive traded for the
far worse false negative. Both rules are pinned by tests that fail if either is removed.

- [x] `resolve/attributes.py`: `AttributeMatch` and `present()`, the one function
      replacing the three duplicated equality tests. `near_names()` narrows and
      **never picks** — choosing between plausible candidates is the comparison ADR-001
      keeps out of a guess's hands.
- [x] `_check_fields_present`, `_check_bound` and `field_constraints._columns` all
      rewritten onto it. `grep -rn "not in stats\|aliases.resolve(header)"` is clean.
- [x] `CheckOutcome.unresolved`, typed rather than folded into the detail sentence.
- [x] Finding type `attribute_not_resolved` in `rules/schema.py`,
      `user-ui/lib/display.ts` and the Findings table in [`design.md`](design.md).
- [x] Stage 7 raises the review record whether or not the check itself failed, so a
      check with both a genuine absence and an unresolved name produces both.
- [x] `*.csv` added to `.gitignore` with the `tests/fixtures/` exception. It blocked
      `*.docx` and `*.xlsx` and not `*.csv`, which ADR-003 plainly intends.
- [x] The `attribute_renamed` fixture: a correct delivery whose DIRT spells every
      attribute the long way. `Case.attribute_spellings` renames the *attribute*, where
      `Case.layout` renames the *structure*.
- [x] **A widening that was not the stated goal, recorded rather than discovered
      later:** routing the three callers through one helper routes attribute names
      through the ladder, which they had never reached. An OSL saying *score* now
      reaches `SCORE_V3` in code where it needed a hand-written alias before. Nothing
      that matched before stops matching, but "only the severity changed" would be
      false. What still needs an alias is what always did — *revolving utilization*
      against `REV_UTIL` — and that is now what the alias test demonstrates.
- [x] ADR-059.
- [x] Tests: `tests/resolve/test_attributes.py` and
      `tests/checks/test_attribute_resolution.py`.

**Not a defect after all.** `scripts/seed_demo.py` and `scripts/load_test.py` appeared
to write alias rows transposed. They do not: `canonical_by_alias` maps alias to
canonical, so only the loop's variable names were the wrong way round and the stored
data was always correct. The names are fixed so the next reader does not reach the same
wrong conclusion.

### 6.22b — The record layout is an artifact · ⬜ not started

The delivered file's record schema, uploaded as a fourth artifact: one row per field
with its name, data type and size, where the field name is what appears as the DIRT
column. It reuses `artifact_types`, so it needs no new admin screen.

- [ ] An `artifact_types` row `record_layout`, built in, **optional**, appearing as an
      upload slot with no front-end change.
- [ ] `parsers/record_layout.py` behind a Protocol (ADR-006), resolving its own headers
      through the ladder so a drifted layout still parses.
- [ ] Uploaded **per run and remembered for the configuration**: promoted on finalize,
      reused when a later run uploads none, and **every finding from a fallback names
      the run and date it came from**.
- [ ] A layout differing from the previous delivery's feeds the drift card.
- [ ] `VersionKind` gains `record_layout`.

### 6.22c — Product codes · ⬜ not started

The OSL may say *"all attributes from ABC"* or name attributes directly. Both must
reach the same check, against the record layout **and** the DIRT.

- [ ] `product_codes` and `product_code_members`. An attribute shared by two codes is
      **one** term with one output name.
- [ ] **Expansion is code, never the model.** The model's only job is reading that a
      requirement names a product code; code looks up the members and code validates
      that the code it was given is one that exists.
- [ ] The `attributes` requirement gains `product_codes` beside `values`.
- [ ] `Run.product_code_attributes`: the expanded list this run used, snapshotted at
      submission. The catalogue keeps **no history** — a run's snapshot is what makes a
      finalized report reproduce, and a re-check that disagrees with the current
      catalogue says so.
- [ ] An attribute delivered beyond the named code's list is a **low**-severity note,
      never a failure. It is also a privacy signal: a field nobody asked for may be PII.
- [ ] Upload as a master file or one file per product code.
- [ ] **Phase 7 refines this**: how a product code is recognised in real OSL prose, and
      what real deliveries carry beyond their code, can only be tuned against real files.

### 6.22d — The dictionary and one resolution path · ⬜ not started

- [ ] `attribute_terms` and `attribute_spellings`: one canonical attribute, a spelling
      per artifact, scoped with the ADR-029 vocabulary, provenance on the spelling.
- [ ] The dictionary compiles into the ladder's **fourth rung**. Nothing in `ladder.py`
      changes; `resolve/layout.py`'s kinds gain `attribute` and `checks/layout.py`'s do
      not, because a dictionary is thousands of rows and a JSON column is the wrong home.
- [ ] A deterministic shortlist before any model call, and a per-run cap on attribute
      locate calls — a **soft** limit inside the existing ceiling, not a new refusal.
- [ ] `attribute_aliases` superseded by a dual-run read and an explicit previewed copy.
      Nothing that matched before stops matching.
- [ ] The two dormant hooks populated: `NamedValue.label_alternates` and
      `ReportSheet.resolve_column`'s alternates.

### 6.22e — What the layout lets us check · ⬜ not started

- [ ] Every attribute the OSL requires — named directly or expanded from a product
      code — appears in the uploaded record layout, using 6.22a's three-state rule.
- [ ] That check and `fields_present` produce **one** alarm between them, with the
      explanation attached.
- [ ] **Out of scope:** type agreement, size and precision, nullability, enum domains,
      regex formats. Those belong on `field_constraints`, which already exists.

### 6.22f — It learns, and a person decides · ⬜ not started

- [ ] `Run.attribute_suggestions` and an accept endpoint, copied from the layout
      suggestions rail.
- [ ] `TrainingObservation` kind `attribute_mapping`: **any user** may propose while
      Train AI mode is on, a reviewer or admin approves, in the **existing** queue.
- [ ] Person-proposed activates on approval; model-read stays in shadow with a review
      record until a reviewer confirms it (ADR-021).

### 6.22g — The docs describe what is true · ⬜ not started

- [ ] `model-context.md`, `architecture.md`, `glossary.md`, `phase-plan.md`, the phase
      table in `CLAUDE.md`.
- [ ] **`design.md` and `CLAUDE.md`: "reconciles three things" becomes four.**
- [ ] `phase-7.md` gains the two refinements named in 6.22c.
- [ ] Both training documents and both Guides rebuilt.

## Acceptance criteria · 🟡 in progress

- [x] 1. A delivery whose DIRT spells every attribute in a long form the OSL does not
      use produces **zero** `report_violates_rule` findings. Measured on
      `attribute_renamed`: **before 6.22a, one high-severity finding naming all ten
      delivered attributes as missing; after, zero** — four `attribute_not_resolved`
      records at `review` instead.
- [x] 2. `grep -rn "not in stats\|aliases.resolve(header)" src/greenlight_ai` returns
      nothing outside the module docstring that quotes the old test.
- [x] 3. An attribute that genuinely was not delivered is still `report_violates_rule`
      at **high**. `attributes_missing_in_report` is unchanged.
- [ ] 4. An OSL naming only product code `ABC` validates every one of ABC's attributes
      against both the record layout and the DIRT; an OSL naming an attribute directly
      validates that name. Both reach the same check.
- [ ] 5. A delivery carrying attributes beyond the named code's list produces a **low**
      note and no failure.
- [ ] 6. Re-checking a finalized run after the catalogue changed uses the run's snapshot
      and says the catalogue has since moved.
- [ ] 7. With a record layout uploaded and an empty dictionary, a run makes at most the
      configured cap of attribute locate calls, recorded in `llm_calls`.
- [ ] 8. The second run of the same configuration, after one accepted suggestion, makes
      **zero** attribute locate calls — asserted by counting calls, not claimed in prose.
- [ ] 9. An OSL attribute absent from the record layout produces **one** finding, not two.
- [ ] 10. A user without admin capability can propose a mapping when Train AI mode is on
      and cannot activate one.
- [x] 11. Nothing in 6.22a can make a delivery pass: the widened test only ever moves a
      finding *down* from high to review, and an attribute nothing resembles is still a
      violation. Code sets every severity (ADR-001).

## Out of scope

- **Bulk import and export of the dictionary.** No import precedent exists anywhere in
  the product, and the record layout removes most of its urgency. It is its own phase,
  after the dictionary has been used for a month.
- **Renaming 6.21b's `layout_*` identifiers.** The concepts are separated by word and by
  identifier instead; a rename touches fourteen files and eight docs for no behavioural
  gain.
- **Batching the model rung.** One call offering many names adds a cross-assignment
  hallucination surface code cannot check. Ship the cap, measure, batch later with a
  benchmark — the discipline 6.21c set by refusing to ship an unmeasured detector.

## Order worth doing it in

6.22a alone, merged and released. Then b (the record layout, which makes the rest
cheap), c (product codes), d (the dictionary both feed), e, f, g.

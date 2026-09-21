# Phase 6.22 — Product codes, the record layout, and attribute resolution

**Status:** 🟡 **in progress** — 6.22a, 6.22b and 6.22d complete and 6.22c built,
2026-09-21. 6.22c leaves two items open and says why under its heading. 6.22e, f and g
are specified below and not started.

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

### 6.22b — The record layout is an artifact · ✅ complete

**Built 2026-09-21**, ADR-060. The delivered file's record schema, uploaded as a fourth
artifact: one row per field with its name, data type and size, where the field name is
what appears as the DIRT column. It reuses `artifact_types`, so it needs no new admin
screen.

**Found while building.** A workbook with no field-name column anywhere must be a
`ParseError` rather than an empty layout. Reading it as empty asserts "this delivery
declares no fields", which is the same conflation of *absent* with *unknown* that 6.22a
had just undone, one artifact along. And a **borrowed** layout must never be
re-promoted: it is already the configuration's, and re-promoting would move the source
run forward to a run that uploaded nothing, so every finding quoting that provenance
would be quoting something untrue.

- [x] An `artifact_types` row `record_layout`, built in, **optional**, appearing as an
      upload slot with no front-end change. `NON_REPORT_KINDS` in `parsers/base.py` is
      now the single place that says which uploaded kinds are not reports; the worker,
      the replay and the credit-date pre-flight read it instead of each carrying their
      own `{"osl", "config"}`.
- [x] `parsers/record_layout.py` behind a Protocol (ADR-006), resolving its own headers
      through the ladder so a drifted layout still parses. A layout headed `Column
      Name` / `Type` / `Length` is the same document as one headed `Field name` /
      `Data type` / `Size`, and a cover sheet before the layout is skipped rather than
      rejected.
- [x] Uploaded **per run and remembered for the configuration**: promoted on finalize,
      reused when a later run uploads none, and **every finding from a fallback names
      the run and date it came from** — `RecordLayoutDocument.provenance`, built from
      `runs.record_layout_run_id` and `runs.record_layout_source_date`, which are stored
      on the run so the clause still reads after the source run is purged.
- [x] A layout differing from the previous delivery's feeds the drift card.
      `drift.diff_record_layout` reports added, removed, retyped, resized and moved,
      matched up the ladder so a respelling is not one field lost and another gained.
- [x] `VersionKind` gains `record_layout`, keyed `customer|configuration_id`. The
      snapshot excludes the source run on purpose: what is versioned is the layout, and
      a second delivery of the same shape is not a new version of it.
- [x] The `record_layout_supplied` fixture: a correct delivery shipping its layout under
      a source system's own headings, declaring two fields the OSL never asked for.
      `attribute_renamed` ships one too, which is the realistic pairing — a source
      system that respells everything documents the respelling.
- [x] ADR-060.
- [x] Tests: `tests/parsers/test_record_layout.py`, `tests/db/test_record_layouts.py`,
      `tests/api/test_record_layout.py`, and the record-layout class in
      `tests/db/test_drift.py`.

**Two defects repaired that were not the point.** `drift_out` never filled
`newly_unchecked`, computed since Phase 6.11c and never once shown on a screen; it is
filled now, beside `record_layout`. And `announcements.validate` counted its five-notice
limit against the wall clock while its tests seeded notices around a frozen `NOW`, so
`test_a_sixth_notice_is_refused_with_the_reason` was green the morning it was written
and red that afternoon — which is how it came to be failing on clean `dev`. The moment
is an argument now, as `showing_now` has always taken one.

### 6.22c — Product codes · 🟡 in progress

**Built 2026-09-21**, ADR-061. The OSL may say *"all attributes from ABC"* or name
attributes directly. Both must reach the same check, against the record layout **and**
the DIRT.

**Found while building.** Expanding at the check was the obvious place and the wrong
one. The golden set caught it: `product_code_named` raised `extra_rule_in_config`,
because stage 6 was asking "does any OSL requirement cover this config element" against
a rule whose `values` were still empty. A requirement that names a code and one that
lists the same attributes state the same thing, so the expansion has to happen **once**,
at the end of stage 2, where every later stage sees the result.

- [x] `product_codes` and `product_code_members`. An attribute shared by two codes is
      **one** term with one output name: the console refuses the save that would create
      a disagreement, and `ProductCatalogue.conflicts` names any that exist rather than
      picking a winner.
- [x] **Expansion is code, never the model.** The model's only job is reading that a
      requirement names a product code; code looks up the members and code validates
      that the code it was given is one that exists. An undefined code becomes an
      `unknown_product_code` check that **fails** — never an empty expansion, which
      would turn "check everything in ABC" into "check nothing" and pass the delivery.
- [x] The `attributes` requirement gains `product_codes` beside `values`, and is the
      one set type that may carry codes instead of values. The extraction prompt goes
      to version 4.
- [x] `Run.product_code_attributes`: the catalogue this run used, snapshotted at
      submission. The catalogue keeps **no history** — a run's snapshot is what makes a
      finalized report reproduce, and a re-check that disagrees with the current
      catalogue says so in a run notice.
- [x] An attribute delivered beyond the named code's list is a **low**-severity note,
      never a failure. It is also a privacy signal: a field nobody asked for may be PII,
      and the note says so. Silent unless a requirement actually names a code.
- [ ] Upload as a master file or one file per product code. **Outstanding.** The
      console creates and edits a code one at a time, which is what a person maintaining
      a handful does. A bulk upload has the same problem the dictionary's does — no
      import precedent exists anywhere in the product — and it belongs with that one,
      after real files have shown what a master file actually looks like (Phase 7).
- [x] The `product_code_named` fixture: an OSL naming `ABC` instead of listing, plus an
      undefined `DEF`, plus two delivered fields the code never listed. The golden set
      seeds `ABC` from the manifest and leaves `DEF` undefined, because an undefined
      code producing a finding is part of the oracle.
- [x] ADR-061.
- [x] Tests: `tests/rules/test_product_codes.py`, `tests/api/test_product_codes.py`, and
      the product-code class in `tests/rules/test_derive.py`.
- [ ] **Phase 7 refines this**: how a product code is recognised in real OSL prose, and
      what real deliveries carry beyond their code, can only be tuned against real files.

### 6.22d — The dictionary and one resolution path · ✅ complete

**Built 2026-09-21**, ADR-062. The answer to the question `design.md` has carried since
Phase 0: *"Is there an attribute data dictionary to seed the alias table?"* This is
where one lives when somebody has one, and where the tool writes down what it learned
when nobody does.

**Found while building, and it is the worst defect this phase has turned up.** · ✅ complete
`context.resolver` was never assigned. Stage 7 built its resolver in a local variable
and `repository.save_context` read `context.resolver`, which was always `None` — so
**every run since 6.21b has stored an empty `layout_suggestions` list**, however much
the model had to reason about. The suggest-then-accept rail ADR-054 describes has never
once been offered something a real run found. Stage 7 assigns it now, which is also what
makes `attribute_locate_calls` reach the database at all.

- [x] `attribute_terms` and `attribute_spellings`: one canonical attribute, a spelling
      per artifact, scoped with the ADR-029 vocabulary, provenance on the spelling —
      on the spelling rather than the term, because it is the spelling somebody
      vouched for.
- [x] The dictionary compiles into the ladder's **fourth rung**. Nothing in `ladder.py`
      changes; `resolve/layout.py`'s kinds gain `attribute` and `checks/layout.py`'s do
      not, because a dictionary is thousands of rows and a JSON column is the wrong home.
- [x] A deterministic shortlist before any model call, and a per-run cap on attribute
      locate calls — a **soft** limit inside the existing ceiling, not a new refusal.
      Past it the run stops asking and names what it did not look for.
      `llm.max_attribute_calls_per_run` sets it; `runs.attribute_locate_calls` counts
      what was spent, so the cap is measured rather than claimed.
- [x] `attribute_aliases` superseded by a dual-run read and an explicit previewed copy.
      Nothing that matched before stops matching, and the copy adds and never removes.
- [x] The two dormant hooks populated: `NamedValue.label_alternates`, threaded since
      Phase 6.15 with nothing ever filling it, and `ReportSheet.resolve_column`'s
      alternates.
- [x] `present()` takes a resolver through a **Protocol** rather than an import, so
      `parsers` does not acquire a model adapter by using this package's normalisers.
- [x] ADR-062.
- [x] Tests: `tests/resolve/test_dictionary.py`, `tests/resolve/test_attribute_cap.py`,
      `tests/api/test_attribute_dictionary.py`.

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
- [x] 7. With a record layout uploaded and an empty dictionary, a run makes at most the
      configured cap of attribute locate calls, counted on the run itself
      (`runs.attribute_locate_calls`) rather than inferred from `llm_calls`, because the
      question is how many *this* run spent and the cap is enforced where they are spent.
- [x] 8. The second run of the same configuration, after the spellings are recorded,
      makes **zero** attribute locate calls — asserted by counting calls, not claimed in
      prose (`tests/api/test_attribute_dictionary.py`).
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

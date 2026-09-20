# Phase 6.14 — The artifacts belong together, and the console says why

**Status:** ⬜ **not started** — specified 2026-09-20 from a review that ran the product
against a deliberately mismatched submission and watched it pass.

**What the review found.** The tool validates a delivery thoroughly and says nothing
about whether the delivery is the one the submitter claims. A run submitted with the
wrong customer, the wrong configuration id and a credit date that appears in none of the
artifacts finished `needs_review` with four ordinary findings and a confident summary.
The evidence was present and parsed — `config.json` carries both `configuration_id` and
`customer` — and nothing compared either with what the submitter typed. The one such
check that exists, the credit date, runs at stage 7 of 9 and greps for the date's *value*
anywhere in any cell, so it cannot report a mismatch and can pass on a coincidence.

Second finding, from the same review: the console tells an administrator *what* a field
is and almost never *what it does to a run*. "Reaches the model" appears as ad-hoc prose
on five screens and nowhere else, in five different wordings. An administrator filling in
AI context, a standing instruction, a guide entry and a configuration note has no way to
know that all four land in the same prompt block, that the block is capped, or that none
of them can make anything pass or fail.

**Goal:** two things, and deliberately not a third.

1. **The artifacts are checked against each other, before validation.** Code compares what the submitter said against what the
   artifacts declare, before the model is asked anything. A mismatch holds the run and is
   shown; a person accepts it with a reason and the run proceeds. Nothing is re-uploaded.
2. **The console explains itself.** Every field that reaches the model says so, in one
   wording, from one component. Tooltips explain intended use, are a setting, and are on
   by default.

**Not** the reference-artifact work. Letting samples inform a run is a real design
question with a measurable answer, and it is specified separately once 6.14a and 6.14b
have shipped and the benchmark can judge it. See "Deferred, on purpose".

Effort 2–3 weeks. Read **ADR-041 (this phase's decisions)**, ADR-001 (code compares, the
model reads), ADR-035 (the fail-closed gate and its attestation — and why this one
departs from it), ADR-029 (scope is one token) and `docs/phase-6.13.md` "The defects, as
found" first.

## The problem, demonstrated

A run submitted on 2026-09-20 against the `geography_extra_state` fixture:

| Field | Submitted | The artifacts declare | Caught |
| --- | --- | --- | --- |
| Customer | `Totally Different Bank PLC` | `Acme Card Services` (`config.json`) | no |
| Configuration id | `CFG-DOES-NOT-EXIST-999` | `CFG-SYNTH-GEO-02` (`config.json`) | no |
| Credit date | `2019-01-15` | absent from every artifact | yes — medium, stage 7 |

The run reached `needs_review` and read as a normal result.

**The blast radius is wider than the miss.** Delivery drift (Phase 6.9) keys on the
configuration id. For this run it reported:

> No earlier finalized run of configuration CFG-DOES-NOT-EXIST-999 for Totally Different
> Bank PLC.

which is indistinguishable from the legitimate "first run of this configuration". A
mistyped configuration id silently disables the drift comparison and looks correct doing it.

**The credit-date check is weaker than it reads.** `_date_spellings` resolves thirteen
spellings of a date's *value* — ISO, slashed US and day-first, padded and not, the month
written out. It resolves nothing about what the field is *called*, and the check searches
every sheet name, header and cell for the value. So it answers "does this date appear
somewhere" and not "does the date the report is cut as of match the one you gave me". It
cannot report a mismatch, and any coincidental occurrence passes it.

## The shape of the answer

### A mismatch is a gate, not a finding

A finding is something a reviewer weighs against other findings. An artifact mismatch is
not that: it is a statement that the other findings may have been computed against the
wrong premise. It belongs before them, and it belongs in the reviewer's line of sight
when they sign.

```
upload ──parse (code, no model)──▶ artifact match check ──▶ queued ──▶ s1 … s9
                                        │
                                   mismatch
                                        │
                                   held, shown
                                        │
                              a person accepts, with a reason
                                        │
                                     queued
```

The gate runs on the parsed config and reports only. Stage 1 parses all seven files of a
run in 14–57 ms, so the gate is synchronous at submit and costs no model call. The run
exists and its files are stored before the gate runs, which is what makes acceptance
possible without re-uploading anything.

**Acceptance is an attestation, not a dismissal.** ADR-035 already established the
shape: the finalize gate holds until every coverage gap is acknowledged, by name, and the
acknowledgement appears on the frozen report. An accepted artifact mismatch is recorded
the same way and appears in the same two places, because a reviewer signing a delivery
should be able to see that somebody waived the question of whether these artifacts belong
together.

### The credit date is resolved by label, then compared by value

Two changes, and the second depends on the first.

**Labels are scoped data.** What a delivery calls its credit date varies: *as-of date*,
*data date*, *cycle date*, *extract date*. These are document labels, not data
attributes, so they do not belong in `attribute_aliases` — which resolves attribute names
and loads as global-plus-customer only, the one table in the product that never adopted
the ADR-029 scope vocabulary. A new scoped table carries them and uses `scopes.py`, so a
programme or a single configuration can name its own spelling.

**The check finds the labelled cell, then compares.** Today: "does this value appear
anywhere." After: "find the cell whose label resolves to the credit date, read its value,
compare." That turns a presence test into a mismatch test and removes the coincidental
pass. Where no labelled cell is found the check degrades to today's search and says which
of the two it did, so a weaker answer never reads like a stronger one.

### The console says what a field does

One component, one wording, three facts per field: **where it goes**, **what it can do**,
and **what it cannot**. A field that reaches the model says so; a field that is compared
by code says that instead; a field that does neither says nothing and is not decorated.

Tooltips explain intended use — what this surface is *for*, how it is meant to be used,
and what belongs somewhere else. They are a setting, on by default, and an administrator
who knows the product can turn them off.

## Scope · 🟡 in progress

### 6.14a — The artifact match check · ✅ complete

- [x] `ConfigDocument` exposes `customer` alongside the `configuration_id` it already
      requires. The parser keeps raising when `configuration_id` is missing; a missing
      `customer` is absence, not a parse error.
- [x] `checks/artifact_match.py`: pure functions comparing submitted against declared for the
      configuration id, the customer and the credit date. No model call, no I/O. Each
      returns the field, both values, and how they were compared, so the screen can show
      the comparison rather than a verdict.
- [x] Customer comparison normalises the way alias lookups do (case, punctuation,
      whitespace, common suffixes) and reports *near* matches distinctly from *different*
      ones. "Acme Card Services" against "ACME Card Services, Inc." is a near match and
      says so; it is still shown, because a reviewer decides.
- [x] A run status `held` and an `artifact_mismatch` table: run, field, submitted,
      declared, kind (`different` · `near` · `absent`), accepted-by, accepted-at, reason.
- [x] `POST /runs` runs the gate synchronously after storing the files. A run with no
      mismatch is `queued` exactly as today. A run with one is `held`, and the response
      carries the mismatches. **No existing clean-submission path changes.**
- [x] `POST /runs/{id}/match/accept`: a reason per mismatch, required and non-empty,
      recorded with the current user; the run moves to `queued`. Accepting is the only
      transition out of `held` besides deleting the run. **Anyone who can submit a run
      can accept a mismatch** — the check exists to put the disagreement in front of the
      person, not to route it to somebody else. Who ought to be consulted before
      accepting is a matter for the delivery process, not a role in the tool (ADR-041).
- [x] The worker refuses to execute a `held` run, so a queue consumer cannot race past the
      gate.
- [x] user-ui: a hold is a state the run is in, not a moment during submission, so the
      panel lives on the **run page** and the form pushes there as it always did. It
      shows both values side by side per field, marks a near match as such, and offers
      four one-click common reasons above a free-text box so the required reason never
      becomes a formality. **Accept and run** clears every mismatch at once. Navigating
      away leaves the run `held` with its files intact. `held` is in the status
      vocabulary of both the badge tone and the label map, so the runs list shows it.
- [x] Accepted mismatches appear on the review screen above the findings, and in the
      frozen report beside the coverage attestation, with who accepted and why. They
      **do not** block the finalize gate: the question was asked and answered once, and
      the report carries the answer forward for the reviewer to weigh (ADR-041).
- [x] Tests: each comparison in isolation; a clean run is unaffected end to end; a held
      run is refused by the worker; acceptance requires a reason; an accepted run runs;
      the frozen report carries the acceptance; the near-match case is reported as near;
      **finalize is not blocked by an accepted
      mismatch**.

### 6.14b — The credit date, resolved by label · 🟡 in progress

- [~] A `field_labels` table: canonical field (a closed set, `credit_date` first), label,
      scope token via `scopes.py`, active flag, author. The built-in spellings live in
      `DEFAULT_LABELS` and are always appended after the configured ones, so a
      deployment that configures none checks exactly as it did before the table
      existed. **Outstanding:** version history and revert, which every other
      definition has (ADR-029).
- [x] `resolve_labels(session, canonical, scope)` returns the labels in force for a run,
      most specific scope first, exactly as examples and samples already resolve.
- [x] The stage-7 check finds a cell whose label resolves to `credit_date`, reads the
      value, and compares it with the submitter's date using the existing
      `_date_spellings`. Outcomes: match (no finding), mismatch (medium, naming both
      dates and where the label was found), no labelled cell (falls back to today's
      search, and the finding says the fallback was used).
- [ ] The artifact match check in 6.14a uses the same resolution, so the date is checked once,
      before the model runs, and stage 7 keeps only what needs parsed reports.
      **Outstanding:** the gate compares the configuration id and the customer, both of
      which come from the one small JSON it already decodes. Moving the credit date
      forward means parsing every report at submit — worth doing, and worth measuring
      the added latency first rather than assuming it.
- [ ] Admin console: the label set under Reference data, with the scope picker every
      other scoped definition uses. **Outstanding:** the table and its resolution work
      and are tested; there is no screen for them yet, so a new label is a database
      row today.
- [x] Tests: resolution honours scope precedence; a mismatch is reported with both dates;
      an unlabelled report still gets the fallback and says so; an unparseable submitted
      date disables the check loudly rather than silently (the smaller defect listed in
      `docs/phase-6.13.md`).

### 6.14c — What every field does to a run · 🟡 in progress

- [x] `docs/model-context.md`: the single register of every field an administrator or a
      user can write, and for each — which prompt block it lands in, which stages read it,
      the cap that applies, and whether code or the model acts on it. Derived from the
      call sites, not from memory. This is the source the UI labels quote.
- [x] One `<FieldEffect>` component in each app, with three variants: **reaches the
      model** (background, never a requirement), **evaluated by code**, and **reference
      only**. One wording each, used everywhere. The five ad-hoc phrasings found in
      `configs`, `config-notes`, `checks`, `artifacts` and `scopes` are replaced by it.
- [~] Artifact **AI context** and programme **standing instructions** carry the marker
      and an explanation. The remaining prompt-reaching fields — configuration notes,
      guide entries, meaning entries, programme rules, examples — are listed in
      `docs/model-context.md` and still need theirs; **outstanding**, carried in the
      session log.
- [ ] Where a cap applies, the field shows what is left, not just the limit — an
      administrator writing the eleventh configuration note should see that the block is
      full before they write it, not after (`MAX_BLOCK_CHARS`, `MAX_PER_STAGE`).
      **Outstanding:** the caps are stated in the marker text, but not yet counted down
      live. Needs the API to report the block's remaining budget for a given run.
- [x] Tests: every variant renders; a field whose registry entry claims a prompt block
      that `docs/model-context.md` does not list fails the test, so the register cannot
      drift from the code silently.

### 6.14d — Tooltips, on by default · 🟡 in progress

- [x] A setting `ui.tooltips` in the `Appearance` group, `default=True`, with its `.env`
      name. Off hides every tooltip in both apps; nothing else changes.
- [x] A `<Tooltip>` primitive in `admin-ui/components/ui/primitives.tsx` and its user-ui
      twin: keyboard reachable, dismissible, readable by a screen reader, and absent from
      the DOM rather than merely hidden when the setting is off.
- [~] Artifact types and Delivery programmes carry one, each naming what belongs
      elsewhere from the overlap table in `docs/admin-training.md`. The other admin
      screens still need theirs; **outstanding**, carried in the session log.
- [x] Tooltip text lives beside the field, not in a central bundle: a field and its
      explanation are edited in one place or they drift.
- [x] Tests: the setting toggles them; a tooltip is reachable by keyboard; the browser
      test opens one on the Artifact types screen.

### 6.14e — The theme locked by default · ✅ complete

- [x] `ui.theme_locked` changes `default` from `False` to `True`. Both apps start on the
      configured default theme and the picker is hidden until an administrator unlocks it.
- [x] The Appearance group says plainly what locking does and that unlocking is one
      switch, so the new default does not read as a missing feature.
- [x] `docs/user-training.md` and `docs/admin-training.md` are corrected in the same
      commit: both currently describe a picker every user can reach.
- [x] Tests: locked by default with no override; an unlocked console restores the picker
      in both apps.

## Acceptance criteria · ⬜ not started

- [ ] A run whose submitted configuration id, customer or credit date disagrees with the
      artifacts is **held before any model call**, and the person sees both values.
- [ ] A held run cannot be executed by the worker until every mismatch is accepted with a
      reason. Any user who can submit can accept; the tool enforces no role.
- [ ] Acceptance never requires re-uploading a file.
- [ ] Accepted mismatches appear on the review screen and on the frozen report, with who
      and why, and **do not block the finalize gate** (ADR-041).
- [ ] A run with no mismatch behaves exactly as it does today, including its cache keys:
      **configuring nothing changes nothing** (ADR-020's standing rule).
- [ ] The credit-date check reports a *mismatch* where it can, not only an absence, and
      says when it fell back to the old search.
- [ ] Every field that reaches the model is marked as such in both apps, in one wording,
      and `docs/model-context.md` agrees with the call sites.
- [ ] Tooltips are on by default and can be turned off from the console.
- [ ] The theme is locked by default in both apps.
- [ ] `black`, `flake8`, `mypy`, `pytest`, both UI gates and `scripts/check_docs.sh` pass.
- [ ] The golden set is unchanged: this phase adds no model call and alters no prompt.

## Deferred, on purpose

**Reference artifacts informing a run.** Samples still never enter the pipeline, and the
mapping interview still reads `samples[0]` while the product allows three. Letting a
sample-derived structural profile — sheet names, labels, JSON paths, and admin-promoted
labelled value vocabularies — reach stages 2, 3 and 4 is the natural next phase. It is
deferred here for one reason: it is the first proposal in this product whose value is
genuinely uncertain, and it is now measurable. Phase 6.11b's benchmark plus a real model
can answer "does this raise precision and recall" instead of anyone arguing it. Two
questions must be settled before it is specified:

- Where ADR-003 draws the line on *vocabularies*. A list of permitted states is a value
  set, not a sample row. A list of account statuses probably is too. A list of names is
  not. The current proposal is that a vocabulary is never extracted automatically and
  only ever promoted by a person with a meaning attached, which keeps ADR-021's rule that
  nothing reaches a run without human approval.
- What it costs. `MAX_BLOCK_CHARS` is 6000 for everything an administrator contributes to
  one prompt, and structural profiles are not small.

**Run date.** Dropped: the credit date is the date the delivery is cut as of, and a
second date with no source in the artifacts would be a field nobody could verify.

**An interactive final report.** The frozen report is frozen by design and never
regenerated (ADR-013). Interactive *review*, before the freeze, is a different surface
from the frozen artifact and neither blocks the other. Specified separately if wanted.

## Decisions taken with the user

Settled on 2026-09-20, before any of this was built (ADR-041):

1. **Anyone who can submit a run can accept a mismatch.** No role, no routing, no second
   person. The check earns its place by showing the disagreement to whoever is standing
   there — that is the whole of its job, and the record of who accepted and why is what
   makes it reviewable afterwards. Who *ought* to be consulted before accepting is a
   delivery-process question and belongs in the rollout plan, not in an authorization
   check in the tool.
2. **The gate does not cross-check history.** A configuration id that is valid but has
   only ever belonged to another customer is a real mis-submission shape, and catching it
   is deliberately out of scope: it needs a second source of truth (the run history), it
   can be wrong for legitimate reasons (a customer renamed, a configuration transferred),
   and the artifact comparison catches the common case on its own. Revisit only with
   evidence that the common case was not enough.
3. **An accepted mismatch does not block finalize.** It is recorded and it appears on the
   frozen report for the reviewer to weigh, and that is all. This is a deliberate
   departure from ADR-035, which made a coverage gap block the finalize gate until
   acknowledged — the reasoning is in ADR-041. One acceptance, at the point the question
   is asked; the report carries it forward.

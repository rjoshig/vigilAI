# Phase 6.23 — The draft that can be finished, and the button that did nothing

**Status:** ✅ **complete** — 2026-09-21. All six parts built, ADR-063 to ADR-067. Two
acceptance criteria were answered by work that landed before them and are ticked with the
correction stated rather than quietly passed; one scope item was superseded by a decision
taken in 6.23c and says so where it sits.

## The goal, in the user's words

> I don't understand what clone run is doing on user-ui. When we clone a run it should
> technically create a same setup in draft mode and let user edit the artifacts and
> other things. I think that's what we wanted.

> What does Re-check button do? If it is confusing we should not have it.

> And we want to have an additional column where we can easily open final report once
> it's generated.

Anything in draft should stay for five days and be deleted thereafter, controllable from
the admin console.

## Where it stops, precisely

### Clone makes a draft, and nothing can ever finish it

`POST /runs/{id}/clone` does most of what it should: it creates `Run(status="draft")`
prefilled with customer, order number, configuration id, notes, credit date, scope and
the suppressions flag, links it by `cloned_from_id`, copies no files, and enqueues no
job. Its own docstring says so.

Then nothing can advance it. The runs router's complete set of write endpoints is
`POST ""`, `POST /{id}/cancel`, `POST /{id}/match/accept`, `PUT /{id}/requirements`,
`POST /{id}/recheck`, `POST /{id}/clone`, `POST /detect-type`. **There is no endpoint
that attaches files to an existing run, edits a run's fields, or starts a draft**, and
`POST /runs` always builds a brand-new queued run. The UI pushes the user to
`/runs/{new_id}`, where the detail page suppresses its whole body for a draft. The row
sits there until the retention purge deletes it **ninety days later**.

On that dead page, **Re-check is enabled** and will enqueue a job against a run with no
files, and **"Generate final report" is enabled** because the gate finds no undecided
findings on an empty draft — the API refuses it, but the tooltip claims every
high-severity finding has a decision. **A draft cannot even be cancelled**: `cancel_run`
refuses anything that is not `queued` or `held`, and there is no delete endpoint.

**The intended design was built once, in the mock, and then lost.**
`mock/user-ui/report.html:21` sends Clone to `new-run.html`, and
`mock/user-ui/new-run.html:20` carries a "Copy from previous run" modal.
[`design.md`](design.md) promises the New run screen offers *"Copy from a previous run"*
and describes clone as *"New run prefilled from this one"*. Neither was built.

### Re-check is an undocumented button that shows nothing

Queuing a job does not change `run.status`, so the detail page's polling never starts:
the user clicks, the button flickers, and the screen is byte-identical. The rebuilt
findings appear only on a manual reload.

Every document describes exactly one use case — *"edit a requirement or a trace link,
then Re-check"* — and `PUT /runs/{id}/requirements` **already queues the re-check
itself**. The standalone no-edit button is documented nowhere: no tooltip, no Guide
entry, no phase note. Its own docstring is the only description of it in the repository.

And it was enabled on a **finalized** run, where a re-check rewrites rules, traces and
findings underneath a frozen report.

## Decisions taken

| Question | Choice |
| --- | --- |
| The standalone Re-check button | **Removed.** The automatic edit path stays — the only case any document describes |
| A clone | Produces an **editable draft**: artifacts and fields, then submit |
| Draft lifetime | **5 days**, set from the admin console |
| At expiry | A **countdown**, then the existing purge deletes it silently |
| Runs list | A **report column**: the verdict, linking to the frozen report |
| Draft access | **Shared**, like every other run |
| Cloning twice | The second click **returns the draft you already have** |

## Scope · 🟡 in progress

### 6.23a — `draft` becomes real, and the guards that implies · ✅ complete

**Built 2026-09-21**, ADR-063 and ADR-066. Pure guards and constants, and it repairs
four defects on its own.

**One condition closed the re-check hole.** `run.status != "needs_review"` covers
`finalized` — the case that mattered, because findings, coverage and reports all refuse a
finalized run and this route was the hole in that — and also `draft`, `queued`,
`running`, `held`, `failed` and `cancelled`, every one of which was accepted silently.

**The finalize lie was in the gate, not on the button.** `gate_state` computed
`can_finalize` from findings alone, so an empty draft came back ready to freeze with no
blocking reason. The same lie was told for queued, running, held, failed and cancelled
runs. Answering it once in `gate_state` made the header button, the report page's card
and the coverage card truthful together; patching the button would have fixed one of five.

- [x] `RUN_STATUSES`, `ACTIVE_STATUSES`, `TERMINAL_STATUSES` beside `RETENTION_DAYS`, and
      the `Run.status` docstring rewritten — it listed six of the eight, omitting both
      `draft` and `cancelled`. **No database `CHECK`**: ADR-017 keeps migrations portable
      and a `CHECK` on this column means a table rebuild per new state.
- [x] A test reads `user-ui/lib/types.ts` and asserts its `RunStatus` union and
      `RUN_STATUSES` name the same eight states.
- [x] `_must_be_reviewable` on both enqueue sites — the standalone endpoint and the
      requirements edit that queues a re-check of its own.
- [x] `gate_state` refuses a run that never reached review, with a reason a person can
      read. `GateState.not_reviewable` is typed rather than folded into the sentence.
- [x] `save_context(..., narrative=False)` from the re-check, which skips stage 9 and so
      wrote an empty summary over the one the full run produced. An explicit flag, not an
      emptiness test, so a run that genuinely summarised to nothing can still say so.
- [x] The cancel audit records the **previous** status. It read `run.status` after
      setting it, so every cancellation in the log said *"was cancelled"*.
- [x] `repository.delete_run` factored out of `purge_expired` — one implementation for
      the purge, for an expired draft and for a discard, so no path forgets to unlink the
      bytes. The purge now counts abandoned drafts apart from runs that reached the end of
      their retention.
- [x] Tests: `tests/api/test_run_lifecycle.py`, and a summary-preservation test that was
      confirmed to fail without the fix.

### 6.23b — The button that did nothing · ✅ complete

**Built 2026-09-21**, ADR-067. Subtractive in name only: taking the button away exposed
that **the path it was supposed to be the fallback for had never been built**.

**`PUT /runs/{id}/requirements` had no caller in either app.** `design.md` has promised
*"Edit a requirement or a link, then Re-check"* since Phase 2 and `user-training.md` told
people to do it, but no screen ever offered it — `grep editRequirements user-ui` found the
client method and its unit test and nothing else. Removing the standalone button without
building the edit would have left no way to ask for a re-check at all, so the matrix row
gained **Fix link**: pick the right configuration element, or *Linked to nothing*, and say
why. The reason is required, because a correction with none is indistinguishable months
later from a misclick.

**Visibility is the queue's answer, not a ninth status.** A re-check rebuilds findings and
leaves the run in `needs_review`, so nothing about the run changes shape while it happens.
Adding a `rechecking` status would have said so in a vocabulary every filter, label, tone
map and type union would then have to learn, for a job that takes seconds.
`JobQueue.pending_for` asks whether a re-check job is queued or claimed, `RunDetail.rechecking`
carries it, and the screen polls on that and reloads its findings on the edge where it clears.

**And it found a third defect.** A failed re-check marked the run `failed` — or `queued`,
while a retry was pending — taking a reviewable run away from the person reviewing it. A
re-check rebuilds findings from rules and traces that are already stored, so the run still
holds everything it had when the job was claimed. The status is now left alone for that one
task; the error is still recorded and the job is still marked failed, so nothing is silent.

- [x] Remove the Re-check button, its handler and `api.recheck`. It had exactly one
      caller and no e2e test touched it.
- [x] Keep `POST /runs/{id}/recheck` — [`design.md`](design.md) documents it — now guarded
      by 6.23a.
- [x] **Make the automatic re-check visible.** `RunDetail.rechecking` from the job queue,
      a banner that says no model is called and nothing decided is lost, and a reload on
      the edge where it clears.
- [x] **Build the edit that queues it**, which no screen had: *Fix link* on a matrix row,
      refused on a finalized run by the same guard as the re-check (ADR-066).
- [x] A failed re-check leaves the run reviewable, with its findings and its status.
- [x] Move the ADR-054 token guard to the live path. `worker/runner.py::recheck_run`
      counted **rows** and warned on every correctly-cached re-check; it counts tokens now,
      as `pipeline/run.py::recheck` already did.
- [x] The training document and the Guide said *"press Re-check"*; they say the comparison
      stages re-run by themselves, and what the screen shows while they do.

### 6.23c — The draft you can actually finish · ✅ complete

**Built 2026-09-21**, ADR-064 and ADR-065. The **New run form finishes the draft**,
which is what the mock built and what [`design.md`](design.md) promises. It reuses the
existing form — its type detection, multi-part slots, field markers and duplicate
dialog — rather than growing a second uploader that would have to be kept correct
alongside it.

**Found while building.** A draft that submits into `held` (its artifacts disagree with
what was typed, ADR-041) took the early return before the expiry was re-stamped, so it
kept the five-day draft window while waiting for a person to accept the disagreement —
and would have been purged out from under them. The expiry is re-stamped as soon as the
run is known not to be a duplicate, before the mismatch branch.

- [x] Five endpoints, each refusing a run that is not a draft with the status named:
      `PATCH /runs/{id}` · `POST /runs/{id}/files` · `DELETE /runs/{id}/files/{fid}` ·
      `POST /runs/{id}/submit` · `DELETE /runs/{id}` (under the typed word, ADR-032).
- [x] `PATCH` uses `exclude_unset`: `""` clears a note, `0` means the submitter did not
      say, an absent key changes nothing.
- [x] Replacing the files of a kind **unlinks the bytes it replaces**.
- [x] **Refactor `create_run` rather than duplicating it** into `_read_uploads`,
      `_admit`, `_store_uploads`, `_finish_submission`. Two copies of the admission rules
      is how they come to differ by which door a delivery entered.
- [x] ADR-005 applies at submit, where the files finally exist. A draft never matches as a
      duplicate, and **a duplicate answer keeps the draft** — deleting it would destroy
      the work in the act of asking about it.
- [x] When the matched duplicate **is** the draft's source, the dialog says so. This is
      what finally gives `cloned_from_id` a reader.
- [x] Clone carries the fields it dropped, and returns an existing draft rather than
      making a second.
- [x] A draft's row in the runs list leads to the editor and reads **Finish**.
- [x] **Drafts are kept out of the runs list entirely** and reached by one toggle
      beside the filters, which carries a count. A draft is unfinished work rather than
      a delivery that was validated, so letting abandoned ones accumulate in the history
      puts noise in front of the runs somebody is looking for. The API excludes them
      unless they are asked for by name, so the exclusion cannot be undone by a screen
      that forgets it.
- [x] `lib/draft.ts` holds the prefill as pure, tested functions — `user-ui` has no
      page-level tests, so the logic lives in `lib/` beside a test file.

### 6.23d — Five days, visible, and retention that is actually read · ✅ complete

**Built with 6.23c on 2026-09-21** — the draft editor's header needed the expiry on the
wire, so the two landed together — and **measured on 2026-09-21**. The tests assert the
windows by changing the number and reading the date, not by grepping for a call: a call is
a claim and a date is a fact.

- [x] **`retention.days` is real.** `repository.expiry_for` resolves it per run (ADR-023),
      and `uploads.max_mb` reaches `store_upload`'s `max_bytes`. Both settings had been
      editable in the console and read by nothing, which is worse than no setting: somebody
      changes it, watches nothing happen, and stops trusting the screen.
- [x] `retention.draft_days`, default 5, in the existing Retention group — it renders in
      the console with no admin-UI code.
- [x] Submitting re-stamps `expires_at` from now, so a draft sat on for four days still
      gets its full retention. Re-stamped **before** the held branch, so a draft whose
      artifacts disagree with what was typed is not purged out from under the person
      deciding about it.
- [x] Stamped once, never recomputed: lowering either setting affects only rows created
      afterwards, and both help texts say so.
- [x] `expires_at` on the wire, with the countdown on the draft row and in the editor.

### 6.23e — Open the report from the list · 🟡 in progress

**Built 2026-09-21.** The verdict is **the report's own**, read from `final_reports`
rather than recounted from the findings — the report is the artifact of record, and a
second count beside it is how two numbers come to disagree.

- [x] The list learns whether a frozen report exists and what it said.
      `RunSummary.report_verdict` is empty when there is none, because *no verdict yet* and
      *it passed* are not near enough to blur.
- [x] Read in **one statement for the whole page**, not a join per row. The runs list is
      the busiest read in the product, and a test pins the statement count so the column
      cannot quietly become N+1 later.
- [x] A **Report** column carrying **OK** or **Not OK**, opening the frozen report in one
      click. `_detail` reads the same row, so a person opening a run never sees a different
      answer from the one on its row — and the finalized flag is now that read rather than
      a second count.
- [~] `draft` in the status filter — **superseded in 6.23c**, which took drafts out of the
      history entirely and gave them their own toggle with a count. Putting *Draft* back in
      the status dropdown would be a second control for the same thing, and the one that
      does not say how many there are. The toggle is the filter.

### 6.23f — The docs describe what is true · ✅ complete

- [x] [`glossary.md`](glossary.md) gained **clone** and **draft run** in 6.23c, and
      **re-check** is corrected: queued by the edit, no button, visible while it runs, and
      leaving the run reviewable when it fails.
- [x] [`design.md`](design.md) — the Review row now describes *Fix link*, the Runs row the
      report column and the drafts toggle, and both endpoints say who calls them.
- [x] [`architecture.md`](architecture.md) — the re-check paragraph says what makes it
      visible and what a failure does not take away.
- [x] [`model-context.md`](model-context.md) — a row for the trace-link correction, which
      is a field a person writes and which reaches no prompt.
- [x] [`user-training.md`](user-training.md) — *press Re-check* replaced by what actually
      happens, and the Report column described on the Runs section. Both Guides regenerated.
- [x] [`phase-plan.md`](phase-plan.md) and the phase table in `CLAUDE.md`.

## Acceptance criteria · ✅ complete

- [x] 1. Clone a finalized run, land on the New run form prefilled, replace a file,
      submit — and it runs. Impossible before: the draft was unreachable by any endpoint.
- [x] 2. A draft can be discarded, and cannot be re-checked or finalized.
- [x] 3. A draft shows a countdown and is gone after the configured window; a submitted
      run keeps the full retention window. Asserted by **setting the window and reading the
      date**, and by driving the purge until an expired draft is a 404 while the run it was
      cloned from is untouched.
- [x] 4. `resolve(session, "retention.days")` and `resolve(session, "uploads.max_mb")`
      both appear in `src/` — in `repository.expiry_for` and `runs.py::_upload_limit`. The
      tests do not grep for them: they change each setting and measure what moves.
- [x] 5. Re-checking a finalized run is refused with 409, as re-reviewing one already is.
      The same guard now refuses a link correction, which is the same act.
- [x] 6. A re-check leaves `run.summary` and `top_issues` intact.
- [x] 7. **Correcting a trace link** shows the re-check happening, without a manual reload.
      Stated as *editing a requirement* when the phase was specified; the screen that would
      have done that did not exist, and building the correction is what 6.23b did. The
      substance — an edit, a visible re-check, no reload — is what is proved.
- [x] 8. The runs list opens a finalized run's report in one click and shows its verdict.
- [x] 9. Cancelling a run audits the status it actually had.
- [x] 10. `grep -rn "Re-check" user-ui` finds no button — only the *Re-checking* banner
      that says one is in flight, and the training text explaining it.
- [x] 11. A run that never reached review reports that it cannot be frozen, and says why —
      for a draft and for a queued, running, held, failed or cancelled run alike.
- [x] 12. **A failed re-check leaves the run reviewable**, with every finding it had. Found
      while building criterion 7 and confirmed to fail before the fix.

## Out of scope

- **Editing a non-draft run.** A submitted run's fields are what its findings were
  computed against (ADR-041).
- **Extending a draft's life, or emailing before expiry.** The countdown is the warning.
- **Copy from a previous run on the blank New run form**, and **Copy one into a new run**
  from Config history — both promised by [`design.md`](design.md) and both still unbuilt.
  Each needs a run picker of its own; clone from the run in front of you is the path
  people take.
- **Cloning a draft**, and **making drafts private to their submitter**. Runs are shared
  by an existing decision; changing that is a product change, not a lifecycle one.

## Order it was done in

6.23a first — pure guards, and it repaired four defects alone. Then 6.23c and 6.23d
together, because the draft editor's header needs the expiry on the wire and there was no
sense stamping a window nothing displayed. Then 6.23b, which was planned as subtractive and
was not: taking the button away exposed that the edit it was the fallback for had never been
built. Then 6.23e. 6.23f throughout.

**Three defects this phase uncovered, none of them its subject.** A failed re-check took a
reviewable run away from its reviewer. `worker/runner.py::recheck_run` counted call-log rows
rather than tokens, so it warned on every re-check that had behaved perfectly — the fix had
been applied to the copy in `pipeline/run.py` that nothing calls. And `PUT /runs/{id}/requirements`
had been documented in `design.md` and taught in `user-training.md` for the whole life of the
product while having no caller in either app.

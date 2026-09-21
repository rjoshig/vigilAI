# Phase 6.23 — The draft that can be finished, and the button that did nothing

**Status:** 🟡 **in progress** — 6.23a complete 2026-09-21. The rest is specified below
and not started.

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

### 6.23b — The button that did nothing · ⬜ not started

- [ ] Remove the Re-check button, its handler and `api.recheck`. It has exactly one
      caller and no e2e test touches it.
- [ ] Keep `POST /runs/{id}/recheck` — [`design.md`](design.md) documents it — now guarded
      by 6.23a.
- [ ] **Make the automatic re-check visible.** The edit path has the same invisibility
      problem: enqueuing changes no status, so nothing polls. Removing the button without
      this leaves the remaining path just as silent.
- [ ] Move the ADR-054 token guard to the live path. The fix was applied to
      `pipeline/run.py::recheck()`, which has no production caller; the executed guard
      still counts rows and warns falsely on every correctly-cached re-check.
- [ ] The training document and the Guide say *"press Re-check"*; they become "the
      comparison stages re-run by themselves".

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
- [x] A draft's row in the runs list leads to the editor and reads **Finish**, and
      `draft` is in the status filter at last.
- [x] `lib/draft.ts` holds the prefill as pure, tested functions — `user-ui` has no
      page-level tests, so the logic lives in `lib/` beside a test file.

### 6.23d — Five days, visible, and retention that is actually read · ⬜ not started

- [ ] **First, make `retention.days` real.** It and `uploads.max_mb` are both editable in
      the console and read by nothing: neither `expiry_from`'s `days` nor
      `store_upload`'s `max_bytes` is ever passed. A new setting added before this fix
      would repeat it verbatim.
- [ ] `retention.draft_days`, default 5, in the existing Retention group — it renders in
      the console with no admin-UI code.
- [ ] Submitting re-stamps `expires_at` from now, so a draft sat on for four days still
      gets its full retention.
- [ ] Stamped once, never recomputed: changing either setting affects only rows created
      afterwards. `retention.days`'s help text claims the opposite today and is wrong.
- [ ] `expires_at` on the wire so the list and the editor can count down.

### 6.23e — Open the report from the list · ⬜ not started

- [ ] The list learns whether a frozen report exists and its verdict; today it can only
      infer "frozen" from the status and carries no verdict.
- [ ] A **Report** column linking to the frozen report; `draft` added to the status filter.

### 6.23f — The docs describe what is true · ⬜ not started

- [ ] [`glossary.md`](glossary.md) gains **clone**, **draft run** and a corrected
      **re-check** — there is no entry for the first two at all.
- [ ] [`design.md`](design.md), [`architecture.md`](architecture.md),
      [`model-context.md`](model-context.md), [`phase-plan.md`](phase-plan.md), the phase
      table in `CLAUDE.md`, [`user-training.md`](user-training.md) and both Guides.

## Acceptance criteria · 🟡 in progress

- [x] 1. Clone a finalized run, land on the New run form prefilled, replace a file,
      submit — and it runs. Impossible before: the draft was unreachable by any endpoint.
- [x] 2. A draft can be discarded, and cannot be re-checked or finalized.
- [ ] 3. A draft shows a countdown and is gone after the configured window; a submitted
      run keeps the full retention window.
- [ ] 4. `resolve(session, "retention.days")` and `resolve(session, "uploads.max_mb")`
      both appear in `src/`. Neither ever has.
- [x] 5. Re-checking a finalized run is refused with 409, as re-reviewing one already is.
- [x] 6. A re-check leaves `run.summary` and `top_issues` intact.
- [ ] 7. Editing a requirement shows the re-check happening, without a manual reload.
- [ ] 8. The runs list opens a finalized run's report in one click and shows its verdict.
- [x] 9. Cancelling a run audits the status it actually had.
- [ ] 10. `grep -rn "Re-check" user-ui` finds no button.
- [x] 11. A run that never reached review reports that it cannot be frozen, and says why —
      for a draft and for a queued, running, held, failed or cancelled run alike.

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

## Order worth doing it in

6.23a first — pure guards, and it repairs four defects alone. Then 6.23b (subtractive).
Then 6.23d, because the editor's header needs the expiry on the wire. Then 6.23c, the
largest piece and the one not to rush: it moves file creation across the duplicate branch
in the busiest function in the API. Then 6.23e. 6.23f throughout, never at the end.

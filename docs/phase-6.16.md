# Phase 6.16 — Numbers that mean something, and which engine answered

**Status:** ✅ **complete** — 2026-09-21. Four small things asked for together, each
correcting a number that was either misleading or missing.

## What was wrong

**"Total runs" only ever grows.** A lifetime counter on the runs screen stops being a
number anybody reads after the first month. What a team works in is the last thirty
days.

**The delivery programme was invisible until you opened a run.** It is how a reviewer
finds the runs that are theirs, and it was a click away from every one of them.

**Nothing said which engine answered.** Phase 6.15 gave stage 6 a model call, so a run
can no longer be described by its token count alone: a run makes calls that produce no
finding at all, and usually does. Asked for during the 6.15 discussion and carried as
outstanding since.

**Nobody could answer what the tool had been worth.** The numbers were in the run
tables; the arithmetic and somewhere to put it were not.

## Scope · ✅ complete

### 6.16a — The runs screen · ✅ complete

- [x] **Delivery programme** as its own column, showing the programme's name and an
      em dash when the submitter did not say.
- [x] **Runs, last 30 days** replaces the lifetime total. Counted in the browser from
      the runs already loaded, so it costs nothing.

### 6.16b — Which engine answered · ✅ complete

- [x] `Finding.engine` — `code` or `model` — on the dataclass, the row, and a
      migration. **Not who decided it**: code sets every severity (ADR-001). It says
      which path reached the answer.
- [x] Three findings are `model`: the compliance locator (6.15), a judgment check's
      verdict, and a lens proposal. Everything else is `code`, which is the default so
      a new finding is code unless it says otherwise.
- [x] A run's statistics report `findings_by_engine`, counted from the stored findings
      rather than inferred from a token count.

### 6.16c — What the tool displaced · ✅ complete

- [x] `value.hours_per_order` in the console, four by default.
- [x] `value_report.py`: distinct **orders** finalized in a period × the hours figure.
      Orders rather than runs, because an order checked three times displaced one
      manual check — counting runs would flatter the number, and a figure that flatters
      is one nobody outside the team will believe. The repeat count is shown beside it
      rather than absorbed.
- [x] Only finalized runs count. A run that failed, was cancelled, or is waiting for a
      reviewer has not displaced anything yet.
- [x] `GET /admin/value-report?start=&end=`, inclusive of both dates, refusing a
      backwards period rather than silently reporting zero.
- [x] A card on the Usage screen with a date range, the figures, and **Save as PDF**.
      Printing is the browser's — a print stylesheet and `window.print()` — rather than
      a second renderer to keep in step with the screen.
- [x] The report states its own assumption: the hours figure, that it was supplied
      rather than measured, and that orders are counted once. A report that hid its
      assumption would be worth less, not more.
- [x] Tests: orders counted once across repeats; unfinished runs excluded; the end date
      inclusive; the hours figure following the console; a backwards period refused.

### 6.16d — Option B from 6.15, reshaped by measurement · ✅ complete

The specification proposed that a rule carry what it looks like in the OSL, the
configuration and the reports. Measuring first changed what was worth building.

- [x] **Measured named values** the way compliance rules were measured. They *are*
      brittle — `Delivered_count` and `Delivered  count` did not resolve against a
      pointer configured as `Delivered count` — but the **consequence is opposite**: an
      unresolvable pointer produces `could_not_evaluate` at **review** severity, an
      honest "I could not check this", where compliance produced a false **HIGH**. Same
      brittleness, safe failure.
- [x] So the answer is the small one, not the new surface: label lookup **normalises**
      case, whitespace, underscores and hyphens, and takes **alternates** — the same
      shape as a compliance rule's, deliberately, so there is one vocabulary rather
      than a seventeenth.

| Report writes | Before | After | With an alternate |
| --- | --- | --- | --- |
| `Delivered count` | found | found | found |
| `DELIVERED COUNT` | found | found | found |
| `Delivered  count ` | — | **found** | found |
| `Delivered_count` | — | **found** | found |
| `Records delivered` | — | — | **found** |

**What this means for 6.15's option B:** it is not built as specified, and should not
be. The problem it was for turned out to be two problems with different severities, and
the severe one was already solved by 6.15's options C and A. What remained was worth
five lines of normalising, not a new authoring surface.

## Acceptance criteria · ✅ complete

- [x] The runs screen shows the delivery programme and a thirty-day count.
- [x] A finding records which path produced it, and a run's statistics count them.
- [x] An administrator can produce a dated report of orders validated and manual hours
      displaced, and save it as a PDF.
- [x] That report states the assumption it rests on, on its face.
- [x] A named value resolves against a label spelled differently, and an unresolvable
      one still says so rather than passing.
- [x] `black`, `flake8`, `mypy`, `pytest`, both UI gates and `scripts/check_docs.sh`
      pass.

## Still open

- [ ] **Do programme rules share the brittleness?** Named values were measured; the
      programme keyword check greps whole words and has not been. The same half hour.
- [ ] The live cap countdown from 6.14c, deferred as a nice-to-have.

# Phase 6.21 — When the shape is wrong, keep going

**Status:** ⬜ **not started** — specified 2026-09-21 from an assessment the user asked
for: *look at the goal objectively, and say where the tool would slip when the real files
arrive.* This is the phase that makes [`phase-7.md`](phase-7.md) survivable.

## The goal, in the user's words

> We validate and find anomalies using documents — Excel, PDF, reports, OSL, JSON config
> — which have a certain format, but the format may be slightly off, so traditional
> programming may not catch some of the anomaly. When traditional comparing or validation
> slips, the LLM should take that over and reason with it, and give me a validation report
> clearly.

Everything else in that statement is built. Artifacts are defined by an administrator,
examples reach the prompts, meaning is mapped between the three artifacts, guides explain
what a cell is, rules are data, and every field says what it does to a run. **The one
sentence that is not built is the middle one.** When the format is slightly off, the tool
does not reason — it stops.

## Where it stops, precisely

The fixed report checks name their sheets and columns as Python constants:

```python
# src/greenlight_ai/checks/reports.py
DIRT_ATTRIBUTE_SHEET: Final[str] = "Attributes"
STATE_SHEET: Final[str] = "States"
FIELD_SHEET: Final[str] = "Fields"
FLOW_SHEET: Final[str] = "Flow"
```

and read the DIRT by exact header text:

```python
header = [h.strip().lower() for h in sheet.header]
name_index = header.index("attribute")          # ValueError → {} → nothing is checked
```

`ReportDocument.sheet()` lowercases and strips, and does nothing else.
`_flow_value()` looks up the labels `Accepts`, `Rejects` and `Input` literally. Named
values normalise a label five ways and then consult a hand-written alternates list.

**A real DIRT whose attribute sheet is called `Attribute Summary` therefore produces one
`could_not_evaluate` finding per requirement and validates nothing.** The finalize gate
refuses to freeze a report until a person acknowledges every one of them
(ADR-035, ADR-036), so nothing is silently missed — the tool is honest. It is also
useless in that state, and a reviewer facing forty "could not evaluate" rows on their
first real delivery will not come back for a second.

This is not a hypothetical. It is the same defect [`phase-6.15.md`](phase-6.15.md)
measured on compliance rules, where `suppressions.lists.ofac` failed to match
`suppressions.ofac` and turned three correct controls into three high-severity findings.
The only difference is the severity it fails at, and that difference is why the report
side was left alone in 6.16d. **It was the right call then and it is the wrong call for
Phase 7**, because at that point the cost is no longer a false alarm — it is a tool that
reports nothing at all about the artifact it was built to read.

## The answer already exists in this repository

6.15 built the shape and 6.17a and 6.18f repeated it. Stated once, so this phase can stop
reinventing it:

1. **Widen deterministically first.** Several tests, OR'd, each removing a real failure.
   Nothing that matched before stops matching.
2. **Ask the model only where code still failed**, and show it *names, never values*.
3. **Code checks the answer.** It must be one of the candidates offered — a name nobody
   offered is a hallucination, and believing one would be the comparison ADR-001 keeps
   out of the model's hands. A confidence floor applies.
4. **It is never a pass.** A model-resolved lookup produces a review-severity record that
   a person confirms.

`checks/compliance_match.py` is step 1, `pipeline/s6_reverse.py::_locate` is steps 2–4,
and `checks/programme_match.py` with `s7_reports._ask_what_it_reads_like` is the second
instance. **This phase applies that shape to the surface where drift actually lands, and
factors it into one module instead of a fourth copy.**

## What else the assessment found

Five things, kept in this phase because they are the same job — being ready to meet a real
file — and because splitting them would mean five documents nobody reads.

| Found | Why it belongs here |
| --- | --- |
| Report layout is code, not admin data | Adapting to a customer's DIRT is an engineering deploy, which is the one thing the product was designed to avoid |
| `profile_anomaly` is declared, labelled in the UI, used in a prompt example, and **never produced** | The user asked for anomalies. Today every finding traces back to a rule somebody authored |
| No cost figure anywhere, and no per-person token accounting | Tokens are counted per call and per day; nobody can see what a run costs or who is spending |
| JSON-schema guided decoding is recommended in [`design.md`](design.md) and not wired up | Phase 7 runs on a 20–40B in-house model. This is the largest reliability lever available and it costs one request field |
| PDF OSL flattens tables into paragraphs | Most `criteria` requirements live in tables. A PDF OSL yields fewer requirements, and "fewer requirements" reads as "nothing wrong" |

## The four decisions this phase rests on

Asked of the user during the assessment, answered 2026-09-21:

| Question | Answer |
| --- | --- |
| What should happen when a sheet or column is not named what the tool expects | **Widen in code, then ask the model.** Code checks the answer, confidence floor, finding stays at review severity |
| What level should the token budget be controlled at | **Show spend, do not block.** The per-run ceiling stays the only hard refusal |
| Should the tool find anomalies no rule covers | **Yes, both ways** — code against the configuration's own history, and one capped model call reading the aggregate shape |
| How much does PDF matter | **The OSL may be a PDF and its tables matter.** Reports stay Excel; no OCR |

---

## Scope · 🟡 in progress

### 6.21a — One resolver, deterministic first, model second · ✅ complete

**Built 2026-09-21.** `src/greenlight_ai/resolve/` holds the ladder; the
`layout_drift` fixture is a correct delivery whose sheets, headers and totals are all
named differently, and `tests/checks/test_layout_drift.py` is the before and the after
on it. Nine of its eleven renamed names resolve in code; two — `Accepts` against
`Accepted total` — share no token once the plural fold has run and need the fifth rung,
which is the case the rung exists for.

**One thing the work found that the specification had not.** The counts report carries
a waterfall step called `input` *and* a total called `Input`. They are different rows,
and the pre-6.21 lookup picked whichever openpyxl happened to return first. Rung 1 now
resolves it by spelling — whichever is written the way the caller wrote it — which is
strictly better than what was there, and falls back to the old first-wins rule only
when spelling does not decide.

A new package `src/greenlight_ai/resolve/` that answers one question — *which sheet,
column or label did they mean?* — and is the only place in the codebase that answers it.

- [x] A ladder, stopping at the first confident answer, each rung named in the result so
      a finding can say which one reached it:
      **exact** (today's behaviour, so nothing that matches now stops matching) →
      **normalised** (case, separators, plurals) →
      **token overlap and ordered subsequence**, borrowing `compliance_match._covers` →
      **administrator-written alternates** from 6.21b →
      **the model**, shown the candidate names only.
- [x] The model rung obeys the 6.15 discipline exactly: names never values, the answer
      must be one of the candidates offered, a confidence floor of 0.6, and
      `engine="model"` on whatever it produces. A run with no client, or one whose token
      budget is spent, falls back to the deterministic answer rather than failing —
      `s6_reverse._may_locate` is the precedent.
- [x] **Never a pass.** A lookup the model resolved produces its ordinary finding *and* a
      review-severity note saying the tool had to reason about the layout, naming what it
      expected, what it found, and how confident it was. A reviewer must be able to
      disagree with the resolution, not only with the finding.
- [x] Wire into the four surfaces that need it: `checks/reports.py` (the four sheet
      constants, the DIRT header lookup, and the `Accepts`/`Rejects`/`Input` flow
      labels), `checks/named_values.py::resolve`, `checks/field_labels.py`, and
      `parsers/base.py::ReportDocument.sheet`.
- [x] **Collapse the four normalisers into this one.** `compliance_match.normalize_segment`,
      `programme_match`, `parsers/base._normalise_label` and
      `field_labels.normalize_label` each implement "lower, strip separators" with
      slightly different rules today. A fifth would be the defect this phase is about.
- [x] One model call per *distinct unresolved name per run*, cached by content like every
      other call (ADR-005), not one per check that referenced it.
- [x] Tests: a fixture set whose sheets and headers are deliberately renamed. Before this
      rung existed it produced `could_not_evaluate`; after it, the checks run and the
      finding says the layout was reasoned about. Plus: an answer not in the candidate
      list refused, a below-floor answer refused, no client degrading to the
      deterministic answer, and every previously-matching name still matching.

### 6.21b — The layout is admin data, not code · ✅ complete

**Built 2026-09-21.** The map lives on the artifact type as ordered entries — scope,
kind, the name the checks ask for, the spellings that also mean it — versioned with
revert like every other definition, and read by the ladder's fourth rung. The
suggestions sit on the same screen: what the model read, how sure it was, why, and how
many runs met it, with one button that records it.

**Building the editor found a defect in it.** The spellings box derived its value from
the parsed list, so every keystroke re-joined the list and ate the space just typed —
"Accepted total" became "Acceptedtotal". The box keeps its own text now and the list
is derived from it, never the other way round. The test that caught it is
`components/layout-editor.test.tsx`.

- [x] A **layout map** on the artifact type: for each thing the fixed checks look for —
      the attribute, state, field and flow sheets; the attribute, min and max columns; the
      `Accepts` / `Rejects` / `Input` labels — what this delivery calls it. Scoped with
      the existing vocabulary (`scopes.py`), versioned through `definition_versions` with
      revert, like every other definition.
- [x] Edited on the existing **Artifact types** screen beside the Guide, not on a new
      one. The console already has fifteen items.
- [x] Marked **Used for setup, not for runs** where it configures, and **Checked by
      code** where it resolves — and `docs/model-context.md` updated in the same commit,
      because a layout name reaches the model in 6.21a's last rung and the register must
      say so.
- [x] **When 6.21a's model rung resolves a name, offer it here as a suggestion an
      administrator accepts with one click** — the shape `GET /admin/keyword-suggestions`
      and its accept endpoint already use. This is how the tool stops needing the model
      call on the second run, and it is the part that makes the product get cheaper as it
      learns rather than more expensive.
- [x] A suggestion is never applied on its own. ADR-021 is unchanged: nothing activates
      without a person approving it.
- [x] Tests: a layout map resolving a renamed sheet with no model call; scope precedence
      (programme over everywhere); revert restoring the previous map; a suggestion
      recorded, listed, accepted, and then short-circuiting the model on the next run.

### 6.21c — Anomalies, both ways · ⬜ not started

The first findings in the product that no person authored a rule for. Both halves produce
low or review severity only, and code sets every severity (ADR-001).

- [ ] **Per-attribute aggregates stored on every finalized run**: null rate, min, max,
      mean and row count per attribute. Aggregates only — no row, no value that is not
      already an aggregate (ADR-003).
- [ ] **Code, against history.** Compare this delivery with the last *N* finalized runs of
      the same configuration and raise `profile_anomaly` when an attribute is far from its
      own history. Sensitivity and *N* settable in the console, with a default that errs
      toward silence.
- [ ] **Silent until it has evidence.** Below the minimum number of prior runs the check
      reports that it has nothing to say rather than inventing a baseline — the same
      discipline [`phase-7.1.md`](phase-7.1.md) applies to the demotion bar.
- [ ] **The model, reading the shape.** One capped call per run, shown the aggregate
      statistics and nothing else, asked what looks unusual. It never decides severity and
      never says whether the delivery is acceptable. Code checks each attribute it names
      was one it was shown, applies a confidence floor, and emits at review severity with
      `engine="model"`. The tripwire scans the assembled prompt like every other call.
- [ ] Both halves are settings an administrator can switch off, defaulting to the code
      half on and the model half off, because the model half spends tokens on every run.
- [ ] `profile_anomaly` stops being a dead finding type: `rules/schema.py:89` has declared
      it since Phase 2, `user-ui/lib/display.ts` labels it, `llm/prompts/s9_summarize.py`
      has an example of it, and nothing in `src/` has ever produced one.
- [ ] A benchmark on synthetic history with precision and recall recorded under
      [`benchmarks/`](benchmarks), following the 6.11 harness. **An anomaly detector
      nobody measured is a false-positive generator**, and this phase does not ship one on
      a promise.
- [ ] Tests: a seeded history with a planted null-rate shift caught; a delivery inside its
      own variance producing nothing; too little history producing a stated silence rather
      than a finding; the model naming an attribute it was not shown refused.

### 6.21d — Spend, visible everywhere · ⬜ not started

No new refusal. The per-run token ceiling stays the only hard stop, as decided.

- [ ] A cost-per-thousand-tokens setting, so the token counts the tool already keeps
      become money. Zero by default, which means the figures stay in tokens and no number
      is invented.
- [ ] **Tokens and cost on the run statistics screen**, with a budget-consumed meter
      reusing `admin-ui/components/cap-meter.tsx` — the countdown built in 6.17b, applied
      to the other budget.
- [ ] **Tokens and cost per person** on Admin → Usage. The per-person table exists
      (`user_usage.py`) and counts runs, failures and holds; it has never counted tokens.
- [ ] **Deployment spend per day and per month** on Admin → Usage, with a warning band an
      administrator sets. A band is a warning, not a gate.
- [ ] The figures state their own assumption, as the value report does: the rate was
      supplied rather than measured, and cached calls cost nothing and are shown
      separately.
- [ ] Tests: cost derived from stored token counts rather than recomputed; a zero rate
      showing tokens and no currency; cache hits excluded from spend; per-person totals
      reconciling with the deployment total.

### 6.21e — The model call itself · ✅ complete

**Built 2026-09-21**, ADR-052. Guided decoding ships on `auto`: the schema goes with
the request, and an endpoint that refuses it costs one wasted call per process rather
than one per stage. The detection tiebreak reuses the ladder's fifth rung and can only
*narrow* the shortlist code already produced — it gets its own verdict, `reasoned`, so
the upload form says the AI read it rather than measured it and still makes somebody
press the button.

**The re-check guard was stale in a way worth recording.** It counted rows in the call
log, and a cache hit is a row. Stages 6 and 7 both gained model calls after it was
written, every one of them cached on a re-check — so the guard would have fired on a
re-check that behaved perfectly. It counts tokens now, which is what "the re-check is
free" has always meant (ADR-051).

The cheapest reliability work in the phase, and the most valuable before Phase 7.

- [x] **Send a JSON schema where the provider supports it.** `llm/openai_compat.py` posts
      only `model`, `messages`, `max_tokens` and `temperature`; `llm/anthropic.py` the
      same. [`design.md`](design.md) has recommended guided decoding since Phase 2 and it
      was never wired up. Behind a setting, degrading silently where the endpoint does not
      understand the field, so an in-house gateway that rejects it is not a broken
      deployment.
- [x] Record whether a call used guided decoding, so the golden set can measure what it
      bought rather than assume.
- [x] **The model tiebreak for ambiguous artifact detection.** `parsers/detect.py`'s own
      docstring says the tiebreak the phase doc allowed was deliberately not implemented.
      It attaches after the deterministic pass returns `ambiguous`, chooses only between
      the shortlist code already produced, and runs on 6.21a's ladder.
- [x] **PDF OSL tables survive as tables.** `parsers/osl_pdf.py` flattens them into
      paragraphs today. Scanned PDFs keep raising a clean `ParseError` — no OCR, which
      stays out of an air-gapped image.
- [x] Fix the stale re-check guard: `pipeline/run.py:181` warns that a re-check must make
      no model calls, but stages 6 and 7 are both in `RECHECK_STAGES` and both can now
      call the model. Either the guard or the stage set is wrong; decide which, in an ADR.
- [x] Tests: a provider that rejects the schema field falling back rather than failing;
      the tiebreak choosing only from the shortlist; a PDF OSL with a criteria table
      yielding the same requirements as the Word original; the re-check guard agreeing
      with reality.

### 6.21f — Show it, and lead somebody through it · ⬜ not started

- [ ] **A dress rehearsal.** "Try this setup against the stored samples" runs the pipeline
      over the artifact type's own samples and shows what it *would* have found, what it
      could not read, and what the guide and meaning entries actually did. Today the only
      way to learn whether a definition works is to run a real delivery. This is also what
      makes 6.21b safe to edit.
- [ ] **A coverage picture** on the review screen and in the frozen report: one bar per
      requirement state — checked, traced but unchecked, manual, untraced. Hand-drawn SVG
      following `admin-ui/components/sparkline.tsx`, which exists precisely so no charting
      library has to. Coverage is badge counts today, on a tool whose pitch is that nobody
      should scan thousands of attributes by eye.
- [ ] **Revive the waterfall.** `report/render.py` passes `waterfall=[]`, so the section in
      the frozen report has always been empty.
- [ ] **A setup path in the admin console.** A "Set up a new delivery" checklist on the
      admin home that walks artifact type → sample → layout map → guide → meaning → check
      → programme, showing what is done and linking to the screen that does it. **Not a
      wizard that hides the screens** — the screens are good; what is missing is an order
      through them.
- [ ] **`<Explain>` in the user app.** Thirteen usages in the admin console, none in the
      user one: a user sees the markers and no help text. Start with the new-run form and
      the review screen's coverage and drift cards.
- [ ] **Confidence on a finding.** `Finding` has no confidence field; the model's own
      number is consumed at a floor and discarded. Carry it so a reviewer can sort by
      least-sure — which is the order a reviewer with forty findings actually wants.
- [ ] Both training documents and both Guides rebuilt (`python scripts/build_guides.py`),
      and `docs/model-context.md` updated, in the commits that change what they describe.

---

## Acceptance criteria · ⬜ not started

1. [ ] A report set whose sheet names and column headers are deliberately renamed runs end
   to end and **produces real findings**, not a page of "could not evaluate". The fixture
   proving it lives in `tests/fixtures/` and the before-and-after is stated in this doc.
2. [ ] Every name the model resolved is visible to the reviewer as a review-severity
   record naming what was expected, what was found, and the confidence — and is offered to
   an administrator as a one-click layout-map entry, so the second run of that delivery
   needs no model call. Demonstrated, not asserted.
3. [ ] `profile_anomaly` is produced by a real code path, and its precision and recall on
   synthetic history are recorded under [`benchmarks/`](benchmarks). A detector without a
   measurement does not count as met.
4. [ ] An administrator can see what a run cost, what a person spent, and what the
   deployment spent this month — and nothing new refuses a submission.
5. [ ] Golden-set accuracy with `LLM_PROVIDER=mock` is no worse than before the phase, and
   the effect of guided decoding is recorded rather than assumed.
6. [ ] One resolver. `grep` finds no second implementation of "lower, strip separators"
   outside `resolve/`.
7. [ ] Nothing in this phase can make a delivery pass. Every model-reached answer is a
   review item a person confirms, and code sets every severity — ADR-001 holds, verified
   by reading the call sites, not the intent.
8. [ ] The docs describe what is true at the commit: this file's boxes ticked,
   `docs/model-context.md` naming every new field that reaches the model and its cap, both
   training documents and both Guides current, and
   `python scripts/update_phase_status.py` clean.

---

## Out of scope

- **PDF reports and OCR.** The decision on record is that Word and Excel are the real
  report inputs. A PDF report reader is a phase of its own if one is ever needed.
- **Per-person or per-programme token blocking.** Visibility was chosen over refusal. The
  per-run ceiling stays the only hard stop, and adding a second one is a decision for
  after somebody has looked at the spend figures this phase produces.
- **Anything in [`phase-7.md`](phase-7.md).** This phase makes the tool *ready* to meet
  real files. It does not meet them, and no real customer file enters this repository
  (ADR-003, ADR-019).
- **6.18b–e.** Still waiting on real verdicts ([`phase-7.1.md`](phase-7.1.md)). Untouched
  by this phase.
- **Reducing what a reviewer sees.** That is 6.18's job and this phase must not
  accidentally do it: every anomaly and every resolved layout is *more* for a reviewer to
  look at, deliberately, until there is evidence it can be trusted.

## Order worth doing it in

**6.21a and 6.21e first** — they are what Phase 7 hits on its first afternoon, and 6.21e
is a day's work for the largest reliability gain available. **Then 6.21b**, which is what
turns a model rescue into a permanent fix. **Then 6.21c, 6.21d, 6.21f.**

## Open questions

- [ ] What is "far from its own history" in 6.21c? A starting number will be picked and
      stated, in the knowledge that only real deliveries can settle it — the same position
      [`phase-7.1.md`](phase-7.1.md) takes on the ten-dismissal bar.
- [ ] Does the in-house serving stack support JSON-schema guided decoding, and at what
      context length? Still open from [`design.md`](design.md)'s open questions, and 6.21e
      is written to degrade cleanly either way.
- [ ] Should a layout map be exportable, so a deployment that has learned one customer's
      layout can hand it to another deployment? Not built until somebody asks.

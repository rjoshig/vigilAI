# Phase 6.11 — Nothing slips: coverage, a fail-closed review, and independent lenses

**Status:** 🟡 **in progress** — specified 2026-09-20 after a review of the product as
built through Phase 6.10; **6.11a complete** the same day. The decisions are in the
table at the foot; the review that led to them is in `docs/session-log.md` (session of
2026-09-20).

**Goal:** a compliance error must not be able to leave the tool as a clean report
because nobody noticed it was never checked, and a reviewer's click must not be able to
say the opposite of what they meant. Three things, in order of how much they matter:

1. **Absence of a finding is not a pass.** The tool tells the reviewer, and the frozen
   report records, which requirements were checked against a report, which were traced
   but never checked, which were never traced, and which can only be verified by hand.
   The finalize gate refuses to close a run with an unacknowledged gap.
2. **A decision says what it means.** OK on a serious finding carries a reason (false
   positive or accepted risk); Not OK carries a comment; the bulk action does what its
   label says; finalizing asks once, with the numbers in front of the person.
3. **The model reads through several lenses, not one.** The stage-8 second opinion
   becomes three independent readers, each a different persona on the same evidence,
   merged by code. They never talk to each other. Where they disagree the finding goes
   to a person with each reason shown.

Effort 2–3 weeks. Read `design.md` "Processing pipeline" step 8 and "Review and final
report", ADR-001, ADR-015, ADR-021, ADR-026, and `llm-privacy.md` before starting.

## The idea

### Lenses, not a debate

The question that opened this phase was whether two or three agents with different
roles, given the same submission, should discuss it for a few rounds before the tool
answers. The instinct is right: **different lenses catch different classes of error**.
A delivery lead reads a report asking "does the output match what was configured"; a
compliance officer asks "which obligation does this breach"; the requirements owner
asks "is this what the specification asked for". One prompt cannot hold all three
stances at once, and a finding one lens waves through another will stop on.

The conversation between the agents is the part this phase leaves out, for four
reasons that hold on this product specifically.

| Reason | Why it matters here |
| --- | --- |
| **Cost** | Three agents for three rounds is up to nine times the calls at that stage, on an in-house 20–40B model where a run already takes five to fifteen minutes. The cache stops helping, because each round's input contains the previous round's output. |
| **Convergence** | Agents that see each other's answers drift toward the most confident one. That removes the independence that made a second lens worth having. Published results on multi-agent debate show modest gains on open reasoning and almost none where the truth is deterministic, which here is every comparison. |
| **Auditability** | A QC record has to say "this finding exists because rule X, evidence Y". "Three personas argued for two rounds" is not reproducible and is hard to defend to a delivery lead or an auditor. |
| **Authority** | The model may not compare or grade (ADR-001, ADR-026). The only thing the agents could debate is meaning, which stages 2, 3, 4 and 8 already isolate into narrow, schema-bound questions. |

So the pattern is **parallel independent readers, merged by code**. Each lens gets the
same finding and the same evidence, answers the same schema, and never sees another
lens. Code merges: agreement raises confidence; any disagreement sends the finding to a
person with every lens's reason attached. A lens may say "this evidence also shows a
problem nobody raised", and that becomes a review item, never a graded finding. A lens
can lower nothing but confidence and raise nothing at all: **the severities code set
stand**. Every call is cached on its own, so a re-run costs nothing and the record of
what each lens said is complete.

The same discipline gives two more places where a model reading through a lens earns
its keep, and neither is a run-time loop:

- **A coverage reader.** Code computes the list of requirements that were traced but
  never checked against a report, and the ones that can only be verified by hand. The
  model reads that list once and says which of them look like compliance obligations
  and why. It proposes; the finding it produces is a review item.
- **A critique pass in synthesis.** After the model drafts a rule from observations, a
  second call asks whether the draft says what the observation said and whether it
  overlaps a rule that exists, and the draft is revised at most once. Admin side, once
  per candidate, both versions kept.

Everything in this phase that touches the model is **switchable per stage, capped per
run, and measured on the golden set before it becomes the default**. The benchmark
harness is therefore part of this phase, and it comes early.

### The gate fails closed

Today the gate (ADR-015) is "every high-severity finding has a decision". It says
nothing about a `review`-severity finding, which is exactly the one the model was not
sure about; nothing about a requirement no report could evidence; nothing about a check
that could not be evaluated; and nothing about a stage-8 verification that failed and
was logged. A reviewer who sees no finding sees a pass. This phase adds a **coverage**
record to every run and widens the gate to it, and finalizing shows an attestation
block the person confirms: what was traced, what was not checked, what could not be
evaluated, which shadow rules were in force, which definition versions applied, and
whether verification ran.

## What exists, and what changes

| Today | After |
| --- | --- |
| `POST /runs/{id}/findings/bulk-ok` writes `review_status="confirmed"` (`api/routers/findings.py`), which is the **Not OK** value everywhere else (`user-ui/lib/display.ts`, `report/render.py`). One click on "Mark all low OK" turns a clean run's verdict to `not_ok`. The test asserts only "not undecided". | The bulk action writes `false_positive`; a test finalizes after bulk-OK and asserts verdict `ok` and every low finding reading OK. |
| Every OK from the review screen is stored as `false_positive` (`decide()` in `app/runs/[id]/page.tsx`); `accepted_risk` exists in `ReviewStatus` and is unreachable. No comment is ever required. | OK asks which: false positive or accepted risk. A reason is required on high and `review` findings; a comment is required for accepted risk and for Not OK on high. |
| Finalize is one unconfirmed button. | Finalize opens the attestation block in `confirm-dialog` and requires the confirm. |
| Gate: every high finding decided. | Gate: every high and every `review` finding decided; every unchecked and manual requirement acknowledged; every `could_not_evaluate` acknowledged. |
| No coverage concept. The matrix shows `missing` for an untraced requirement and nothing for a traced requirement no report check ever reached. A custom report with no guide or meaning entry silently has zero checks. | A `coverage` record per run, computed in code after stage 7, on the review screen and in the frozen report; a report with zero checks applied is a warning. |
| Stage 8: one second-opinion call per high finding; on `LLMError` the finding is kept unchanged and a warning is logged. | Three lens calls per high finding, merged by code; a failed or skipped verification is a run-level notice the reviewer sees and the attestation records. |
| Stage 4 receives the validation guides but not the preamble, so a programme's standing instructions never reach tracing. The preamble clips each field to 1500 characters but the total is unbounded in the number of configuration notes; the guide block is unclipped. | Stage 4 receives the preamble; the preamble and the guide block have a total cap, oldest configuration notes dropped first with a logged count. |
| Synthesis detects overlap with existing rules and stores it on the candidate; approving a conflicting candidate is not blocked. | Approving a candidate with an unresolved conflict requires choosing **supersede** the old rule or **reject** the new one. A critique pass runs once after the draft. |
| The golden set reports pass/fail per case. | The golden set reports precision and recall per finding type per programme, with a pipeline-variant switch so any stage change can be compared against the default. |

## Scope · 🟡 in progress

### 6.11a — Review defects and decision quality · ✅ complete

- [x] `bulk_ok_low_severity` writes `false_positive`, and its docstring says so. A test
      drives submit → bulk-OK → finalize and asserts verdict `ok` with every low finding
      reading OK. **No fixture case produces a low-severity finding**, so the existing
      bulk test had always passed on zero rows; the tests now create one
      (`_add_low_finding`) and so actually exercise the path.
- [x] The review screen offers three decisions outright — **False positive**,
      **Accepted risk**, **Not OK** — rather than an OK button that silently chose one.
      Before this, every OK was stored as `false_positive` and `accepted_risk` was
      unreachable from the screen.
- [x] Reason required: `decision_problem` in the findings router refuses (422) a Not OK
      on a high or `review` finding with no comment, and an accepted risk with no
      comment at any severity. `decisionProblem` in `user-ui/lib/display.ts` is the same
      rule, so the reviewer is asked before the request instead of losing what they
      typed to a rejection. A false positive needs no comment: the choice is the reason.
- [x] Bulk OK stays low-only, records `false_positive`, and is audited as today.
- [x] Finalize uses `components/confirm-dialog.tsx`, with the severity counts and what
      freezing means as its body. The attestation block replaces that body in 6.11d.

### 6.11b — Benchmark harness · ⬜ not started

- [ ] Golden-set fixtures carry **expected findings** (type, leg, the value or member
      that differs) beside the expected rules they carry today.
- [ ] `scripts/golden_set.py` reports **precision and recall per finding type and per
      programme**, plus extraction accuracy as today, and writes the table to
      `docs/benchmarks/`. Shadow findings are excluded on both sides.
- [ ] A **pipeline variant** switch (`LLM_PIPELINE_VARIANT`, default `default`) that the
      stages read where they branch, so a change can be run beside the default on the
      same fixtures and the two tables compared. The variant name is part of every
      cache key it affects (ADR-005).
- [ ] Two new golden cases: a requirement no report can evidence (an `other` clause
      and a `quantity` with no counts report), and a custom report type with no guide,
      no meaning entry, and no named value. Both must appear in coverage, not as
      silence.

### 6.11c — Coverage · ⬜ not started

- [ ] `pipeline/coverage.py`: after stage 7, each requirement is one of `checked`
      (at least one report check evaluated it), `traced_unchecked` (traced to the
      configuration, no report check reached it), `untraced` (no configuration element),
      `manual` (`req_type` `other`, or a check that returned `could_not_evaluate`). Each
      report gets the number of checks that applied. Pure code, no model call.
- [ ] Stored on the run (`run_coverage`, one row per requirement plus per-report
      counts) and returned by `GET /runs/{id}/coverage`.
- [ ] A run-level **notices** list on the run: stage-8 verification failed or was
      skipped for N findings; the programme reading failed; the token budget stopped a
      stage. Reviewers see them; the attestation records them.
- [ ] Review screen: a **Coverage** panel above the findings with the four counts, the
      unchecked and manual requirements listed with their OSL reference, and a warning
      per report with zero checks. The matrix gains a coverage column.
- [ ] Frozen report: a **Coverage** section, computed at finalize and frozen.
- [ ] The stage-9 summary receives the coverage counts as data and is told to name
      what was not checked. It still adds, drops, and re-ranks nothing.
- [ ] Drift (6.9) gains "requirements newly unchecked since the previous run".

### 6.11d — The fail-closed gate and the attestation · ⬜ not started

- [ ] `_can_finalize` (`api/routers/runs.py`) requires: every high and every `review`
      finding decided; every `traced_unchecked` and `manual` requirement
      **acknowledged**; every `could_not_evaluate` finding acknowledged. The gate is
      enforced in the API at finalize time (409), not only in the UI.
- [ ] **Acknowledge** is a per-item action on the Coverage panel with an optional
      note, attributed like a review decision. Bulk acknowledge for the unchecked list
      under one confirm, never for `manual` items.
- [ ] The **attestation block**: requirements traced / unchecked / untraced / manual;
      `could_not_evaluate` count; shadow rules in force (count, with a link on the
      admin side); definition versions in force (6.8 already records them); notices;
      the lenses that ran. Shown in the finalize confirm dialog and stored on
      `final_reports.attestation` (JSON), rendered in the frozen report.
- [ ] ADR-035 amends ADR-015 with the wider gate.

### 6.11e — Independent lenses at stage 8 · ⬜ not started

- [ ] Three registered prompts (`llm/prompts/s8_lens_delivery.py`,
      `s8_lens_compliance.py`, `s8_lens_requirements.py`) sharing one schema:
      `VerifyResponse` plus an optional `missed` list of `{title, reason,
      confidence}`. Each system prompt frames the persona and repeats the rules: judge
      only the evidence shown, never recompute, disagree with a reason. Worked examples
      per lens. Text and aggregates only, never a row (ADR-003).
- [ ] `s8_verify.py` calls each lens independently on the same rendered evidence,
      each cached under its own prompt version. **Code merges**: all agree →
      `verified`, confidence = the minimum; any disagreement → severity `review`, the
      finding's detail names the lens that disagreed and why; the full set of opinions
      is stored on the finding (`lens_opinions` JSON) and shown in the evidence panel.
- [ ] A `missed` item becomes a new finding of type `lens_proposed`, severity
      `review`, leg from the lens, evidence pointing at the same finding's evidence.
      Never graded, never verified again.
- [ ] `LLM_VERIFY_LENSES` (default the three; `single` restores today's one prompt;
      empty disables verification and produces a notice). A per-run cap on lens calls
      beside the token budget; past the cap, remaining high findings are unverified
      and the notice says so.
- [ ] A lens that fails (`LLMError`) is recorded in the opinions as "did not answer"
      and counts as neither agreement nor disagreement; two answering lenses that
      agree still verify. Zero answering lenses is a notice.
- [ ] Stage 4 receives `preamble(guidance, "config")` beside the guide block. A total
      cap on preamble plus guide block, with the oldest configuration notes dropped
      first and the count logged.
- [ ] Measured: the golden set under `default` and under the lenses, both tables in
      `docs/benchmarks/`, before the lenses become the default in `.env.example`.

### 6.11f — The coverage reader · ⬜ not started

- [ ] One cached call per run over the `traced_unchecked` and `manual` list: each
      requirement's type, OSL reference and source text, nothing else. The model says
      which look like obligations (compliance, regulatory, contractual) and why, with a
      confidence. Prompt `s7_coverage.py`, registered and in the prompt suite.
- [ ] Each becomes a finding of type `coverage_gap`, severity `review`, evidence the
      OSL reference. A gap under the confidence floor stays in the coverage list only.
- [ ] Off when `LLM_VERIFY_LENSES` is empty. Counted in the benchmark as its own
      finding type.

### 6.11g — A critique pass in synthesis · ⬜ not started

- [ ] After `synthesize()` drafts a candidate, one call (`synthesize_critique.py`)
      receives the observation statements (as data, delimited as today) and the draft,
      and answers: faithful to the statements or not, with what is missing or added;
      overlaps a listed existing rule or not. At most **one** redraft follows. The
      critique and both drafts are stored on the candidate; the diff at approval
      (ADR-021) is measured against the final draft.
- [ ] Approving a candidate whose `conflicts` is non-empty requires the administrator
      to choose **supersede** (the old rule is disabled with the candidate named as
      its successor) or **reject**. Approve alone is refused by the API.

### 6.11h — Documentation and tests · ⬜ not started

- [ ] ADR-034: lenses, not debate; a lens changes confidence only; a lens proposal is
      a review item; the four reasons above.
- [ ] ADR-035: the fail-closed gate and the attestation, amending ADR-015.
- [ ] `design.md` step 8 and "Review and final report"; `architecture.md` stage table
      and the `coverage` module; `llm-privacy.md` (five new prompts, text and aggregates
      only); `glossary.md` (lens, coverage, acknowledge, attestation, variant);
      `user-training.md` and `admin-training.md`; `gd-rollout-plan.md` readiness list
      and measurement section (precision and recall now come from the harness).
- [ ] Tests per module as usual, plus: bulk-OK then finalize gives verdict `ok`; a
      high finding OK without a reason is refused; a run with one unchecked requirement
      cannot finalize until acknowledged, and the attestation names it; three scripted
      lenses agreeing verify a finding and one disagreeing sends it to review with
      every reason stored; a `missed` proposal becomes a `review` finding and never a
      graded one; a failed lens does not block the other two; the coverage reader on a
      run with nothing unchecked makes no call; a conflicting candidate cannot be
      approved without supersede or reject; the harness reports precision and recall
      on the synthetic set and the two coverage cases appear.

## Acceptance criteria · 🟡 in progress

1. [x] "Mark all low OK" on a run with only low findings, then finalize, gives a report
   whose verdict is OK and whose findings all read OK.
2. [x] A high finding cannot be marked Not OK without a comment, and an accepted risk
   cannot be recorded without one at any severity, from the screen or the API.
3. [ ] A run with a requirement no report evidenced shows it in the Coverage panel,
   cannot be finalized until it is acknowledged, and the frozen report's attestation
   lists it with the acknowledging person's name.
4. [ ] A custom report type with no checks defined produces a coverage warning, not
   silence.
5. [ ] With the three lenses on, a high finding they all agree on is verified with the
   lowest confidence; one they split on goes to review with each lens's reason visible
   in the evidence panel; the severities code set are unchanged in both cases.
6. [ ] `LLM_VERIFY_LENSES=single` reproduces today's stage 8 call for call.
7. [ ] The golden set prints precision and recall per finding type under `default` and
   under the lenses, and the two tables are in `docs/benchmarks/`.
8. [ ] A candidate rule that overlaps an active rule cannot be approved without
   choosing supersede or reject.
9. [ ] Every existing test still passes.

## Decisions (2026-09-20)

Answered by the user in the review session.

| Question | Decision |
| --- | --- |
| A debate loop between two or three agents | **No.** Independent lenses that never see each other, merged by code. |
| Which lenses | **Delivery, Compliance, Requirements owner**, at stage 8 first. |
| What a lens may change | **Confidence only.** Agreement raises it; disagreement downgrades to review as today; a proposal is a review item; no severity ever goes up. |
| The finalize gate | **Fail-closed with an attestation**: high and review findings decided, unchecked and could-not-evaluate items acknowledged, a confirm showing the counts. |
| A second approver (four-eyes) on must-breaches and compliance findings marked OK | **Deferred** to a later phase. It needs login on (ADR-022) to mean anything. |
| One admin front door and one scope vocabulary | **Phase 6.12**, its own doc. Named below. |
| Order against browser tests in CI | **6.11 first**, benchmark harness inside it right after the review defects; browser tests follow. |

## Deferred, with the reason

- **Four-eyes.** A programme-level switch requiring a second approver before finalize
  when a `must` programme breach or a compliance finding was marked OK. Deferred
  because it is only meaningful with login on, and the gate above closes the larger
  hole first. Carry into the "Resume here" block until it has a phase.
- **Phase 6.12 — one front door for the admin console.** Sixteen surfaces feed a run
  today, with three scope vocabularies (`scope_code`, the `scope` string, and
  `customer_name`), three ways to locate a report cell (guides, meaning entries, named
  values) and three ways to say "this must hold" (programme rules, compliance rules,
  judgment checks). 6.12 adds one entry point, "tell the tool something", where the
  model classifies a statement onto the existing surface and drafts it for the
  administrator to confirm into shadow, and unifies the scope vocabulary to one token
  (ADR-029 already says one). The expert screens stay.

## Found on the way

Two things turned up while fixing 6.11a and are worth carrying into the rest of the
phase rather than losing in a commit message.

- **No fixture case produces a low-severity finding**, so the bulk-OK test had never
  run the code it named. 6.11b's golden-set work adds a case that does, and any future
  test about severity should assert the row count it expected to touch.
- **Every fixture case, including the clean baseline, carries two `could_not_evaluate`
  findings at `review` severity**, and the gate lets all of them through undecided.
  That is exactly the hole 6.11c and 6.11d close, now confirmed on real output rather
  than argued from the code.

## Still open

- The confidence floor under which a `coverage_gap` stays in the list rather than
  becoming a finding: start at the existing 0.5 breach floor and tune on the harness.
- Whether `traced_unchecked` should split "no check exists for this type" from "a
  check exists and did not reach this report", once the real report layouts are seen
  (Phase 7).

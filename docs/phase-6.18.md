# Phase 6.18 — Trust that is earned, measured, and revocable

**Status:** 🟡 **in progress** — specified 2026-09-20 from the product goal the user
stated directly: *a reviewer should not have to look at every validation point; as the
tool learns, they should see only the real ones.* **6.18a is built and running in
shadow** — everything it decides is recorded and acted on by nobody, which is the point
— **and 6.18f is built**, closing the last false high-severity finding 6.17a measured.
6.18b, c, d and e wait on real verdicts, which is [`phase-7.1.md`](phase-7.1.md).

**This is the phase that decides what the product is worth.** Everything up to here
makes the tool correct. This makes it *usable at volume* — the difference between a
reviewer reading forty findings and a reviewer reading three.

## The goal, in the user's words

> Initially, in Train AI mode, careful users and specialist administrators define the
> rules and review the QC items. Once that is set, the tool should be trustworthy enough
> that it only surfaces a real QC issue. A human should not need to look at every
> validation point — eventually only the high and critical ones.

That is achievable, and nothing in the current architecture stands in the way. What is
missing is not permission; it is the machinery that makes reducing review **safe,
measured, and reversible**.

## The misreading this phase exists to correct

ADR-021 says a person approves a **rule** before it activates. That has been read, in
conversation and in at least one design discussion, as *a person must see every
finding*. **It does not say that, and the difference is the whole phase.**

| The gate | Where it is | Does it shrink as trust grows |
| --- | --- | --- |
| Approving a rule | Once, per rule, by a specialist | **No.** It stays. It is what makes a finding defensible. |
| Signing off a delivery | Once, per delivery, at finalize | **No.** The attestation is the product's signature. |
| Looking at each finding | Today: every finding, every run | **Yes — this is what this phase reduces, toward zero.** |

Approving a rule is precisely the act of saying *"apply this from now on without asking
me again."* A tool that keeps asking has wasted the approval.

**Equally, the model is not a fallback here.** ADR-001 is often summarized as "code
first". What it says is that the model **reads and judges meaning** and code **does every
comparison**. The model understanding a delivery's context, its programme, and the rules
a specialist taught it *is the product*. This phase leans on that, and takes nothing away
from code: code still does every comparison, and code still sets every severity.

## What already exists, and is not yet connected

The parts have been built one phase at a time and have never been wired into a ladder:

| Built | Where | What it gives this phase |
| --- | --- | --- |
| Shadow state | ADR-021, `training/lifecycle.py` | A rule runs and is counted while showing nobody — precision becomes knowable before it interrupts anyone |
| Fired / dismissed counters per rule | `api/routers/training.py` | The raw evidence: *this rule fired 40 times and reviewers waved 38 through* |
| Bulk-OK on low severity | `api/routers/findings.py` | The crudest version of "do not make them click forty times" |
| Benchmark harness with precision and recall | Phase 6.11 | The means to state trustworthiness as a number |
| `Finding.engine` — `code` or `model` | Phase 6.16b | Which path produced a finding, so the two can be measured apart |
| Decision reasons on a review | Phase 6.11 | *Why* a reviewer dismissed something, not just that they did |

**Nothing acts on any of it.** The counters are displayed and then ignored. That is the
gap this phase closes.

## Scope · 🟡 in progress

### 6.18a — Findings that learn their own severity · ✅ complete

Built 2026-09-20. **It computes, records, and changes nothing anybody sees** — the
decisions are in ADR-043 and the reasoning lives in `training/demotion.py`.

- [x] A **finding signature**: one customer, one delivery programme, one rule, and one
      thing it fired on. Not the run, not the wording. Trust is shared across a
      customer's deliveries within a programme and never across programmes, because a
      control genuinely is implemented differently under Account Solicitation than
      under Archives. The thing it fired on is part of the identity: a blank score
      column and a blank state column share a rule and are not the same finding.
- [x] A **verdict history per signature** — occurrences, dismissals, upholdings, the
      severities it has fired at, and the runs the evidence came from. Undecided
      findings are not counted: a finding nobody judged says nothing about whether it
      mattered. Findings from a rule in **shadow** are not counted either, or a rule
      nobody was shown could demote itself.
- [x] A signature waved through **ten times with no exceptions** is marked
      `would_demote`. A count, not a rate: *"shown to a person ten times and never once
      mattered"* is a sentence that survives an auditor; *"nine times out of ten"* is
      not, because the tenth is the one that would have been hidden. Settable upward.
- [x] **One upheld finding blocks the signature permanently**, until a person clears it.
      `accepted_risk` counts as upheld — the reviewer agreed it was true and chose to
      carry it, which is the opposite of saying it should never have been raised.
- [x] Computed by **code from the counts** (ADR-001). The model is not asked whether a
      finding is important, and its confidence is not evidence here.
- [x] Every state records **which runs' verdicts justified it**, and one sentence saying
      why, so a decision can be shown rather than asserted.
- [x] **`high` and above are never demoted**, at any level of evidence — the floor from
      6.18d, brought forward because it is cheap and it is a safety property.
- [x] **Nothing returns on its own.** A new verdict upholding the finding un-demotes it
      immediately; otherwise a person restores it. ADR-021's rule that nothing in the
      training record expires by itself.
- [x] `GET /admin/demotion-report` — what demotion *would* do, narrowable to a customer
      or a programme, with `shadow: true` on every response while that is the truth.
- [x] **A test asserts that a signature at `would_demote` still puts its finding in
      front of a reviewer**, undecided, exactly as before. That property is the whole of
      6.18a, and it is the one a future change is most likely to break quietly.

**Promotion — a signature people keep escalating getting louder — is specified above
and is not built.** It changes what a reviewer sees, so it belongs with 6.18b's maturity
levels rather than ahead of them, and unlike demotion there is no safe shadow version of
making something noisier.

**What to do with this before building 6.18b.** Let it run for some weeks and then open
the report and ask the question it exists for: *it would have hidden these — was any of
them real?* That answer, not this code, is what says whether the rest of the phase
should be built as specified.

### 6.18b — A maturity level per customer or configuration · ⬜ not started

Demotion should not creep up on anybody. It needs a dial a person sets and can see.

- [ ] A **maturity level** on a configuration (and inheritable from a customer):
      roughly *training* → *supervised* → *trusted*. The names matter less than that
      there are few of them and each says plainly what a reviewer will see.
- [ ] The level is set by an **administrator, deliberately**, and the console states
      what changes at each level. **The tool never promotes itself** between levels —
      it may *recommend* a promotion, with the evidence attached.
- [ ] The level is **visible on the review screen and on the frozen report**. A report
      that does not say how much was auto-decided is a report that overstates itself.
- [ ] Dropping a level is instant, takes effect on the next run, and needs no
      justification. **Trust must be cheaper to withdraw than to grant.**
- [ ] A run records the level in force when it was submitted, like it already records
      the standing notes, so a finalized report cannot change meaning afterwards.

### 6.18c — Trustworthiness as a number · ⬜ not started

The gate on 6.18a and 6.18b both. **Nothing is allowed to be demoted on a feeling.**

- [ ] A **trust report** per configuration: of everything auto-demoted in the last N
      deliveries, how often did a person later disagree? That figure, dated, with the
      sample size beside it.
- [ ] The console **refuses to raise a maturity level** until there is enough evidence
      at the level below — a minimum number of deliveries and a minimum agreement rate,
      both settable, both shown.
- [ ] The existing benchmark harness (6.11) is extended to report **what demotion would
      have hidden**, run against the golden set. A demotion rule that hides a planted
      defect fails the build.
- [ ] The measurement distinguishes `code` findings from `model` findings (6.16b), so a
      drop in quality can be attributed rather than guessed at.

### 6.18d — Nothing is hidden without a record · ⬜ not started

The condition on all of the above, and the thing that makes it defensible six months
later.

- [ ] A demoted finding is **still evaluated, still stored, still in the audit log**,
      with the reason it was not surfaced. Demotion changes what a reviewer is *shown*,
      never what the tool *did*.
- [ ] The frozen report states how many findings were auto-decided and at what maturity
      level. One line, always present.
- [ ] Any finding a person has ever marked **Not OK** for a signature makes that
      signature ineligible for demotion until a specialist clears it. One real escalation
      outranks any number of dismissals.
- [ ] **Severity floor:** `high` and anything above it are **never** auto-demoted, at
      any maturity level. The goal is that a reviewer sees only high and critical — not
      that they eventually see nothing.

### 6.18e — The sample that keeps it honest · ⬜ not started

The failure mode of this whole phase: as people stop looking, the signal that would tell
you the tool has drifted stops arriving. You find out from the customer.

- [ ] A settable percentage of deliveries — small, perhaps 2% — is **reviewed in full
      regardless of maturity level**, chosen at random by code, and marked as a sample
      run so the reviewer knows why they are seeing everything.
- [ ] Sample runs are what 6.18c measures. They are the only source of an unbiased
      disagreement rate, because every other run's evidence is filtered by what the tool
      chose to show.
- [ ] A maturity level whose sample disagreement rate crosses a threshold **drops
      automatically**, and says so loudly. This is the one automatic move in the phase,
      and it is automatic in the safe direction only: **the tool may revoke its own
      trust; it may never grant it.**

### 6.18f — The first worked instance: the programme check · ✅ complete

Built 2026-09-20. ADR-045 holds the decisions; the shape is `phase-6.15.md` option A's,
applied to a second surface.

Phase 6.17a repaired the keyword check deterministically and took its false
high-severity findings from five to one. The one left was never a spelling problem, so
no normalising rule could reach it: a *promotional acquisition mailing* that suppresses
`existing accounts` carries two of Account Monitoring's words and none of its own, and
what makes them innocent is that they appear under *suppress*. That is meaning.

- [x] The keyword check runs first and a hit costs **no model call**, which is what
      makes asking affordable: one call per delivery, only where the keywords missed.
- [x] The model is asked *which of these programmes do these documents read like, and
      which words say so* — **never** whether the submitter was right, which is a
      comparison and is code's (ADR-001). The prompt says the deterministic match has
      already failed and that `unclear` is a good answer.
- [x] Code refuses a programme nobody offered, an answer below a confidence floor, an
      unparseable reply, and no reply. Each falls back to the deterministic answer, so
      **asking is never worse than not asking**.
- [x] Code decides what a believable answer means. The model disagreeing is the
      high-severity finding the check exists for. The model agreeing where code had
      only *"none of its words appear"* is silent, because that was a word-list gap and
      not a reviewer's problem.
- [x] **The model may soften a high-severity finding and may never erase one.** Where
      code had enough to name a different programme, agreement drops it to review
      severity rather than silence: a model agreeing with the submitter is the one
      answer that could hide a real mismatch, so it buys a question. Its own test.
- [x] When the model agrees, the phrases it quoted are recorded on the run and offered
      on the programme's card in the console. Accepting one adds it to the word list,
      after which **the check matches in code and the model is not asked again** — the
      tool stops asking because code now knows, not because the model grew confident.
- [x] Nothing is applied by the run (ADR-021), with a test saying so.
- [x] `docs/model-context.md` records that a delivery's own words now reach a model at
      stage 7, capped, never a data row, and that the prompt is told not to quote a
      phrase containing a person's details.

## Acceptance criteria · ⬜ not started

1. [ ] A reviewer on a *trusted* configuration sees materially fewer findings than the
       same delivery produces on a *training* one, and can reach every suppressed
       finding in one click.
2. [ ] No finding at `high` or above is ever auto-demoted, proven by a test.
3. [ ] A signature with any Not OK in its history is never demoted, proven by a test.
4. [ ] The console refuses a maturity promotion without the evidence, proven by a test.
5. [ ] The golden set passes with demotion enabled: **no planted defect is hidden**.
6. [ ] The frozen report states the maturity level and the auto-decided count.
7. [ ] A sample run is reviewed in full and is labelled as a sample.
8. [ ] Sample disagreement above the threshold drops the level automatically, proven by
       a test.
9. [ ] `docs/model-context.md`, both training documents, and
       [`gd-rollout-plan.md`](gd-rollout-plan.md) describe the maturity levels and what
       each shows — a reviewer must be able to find out why they are seeing less.
10. [ ] An ADR records the decision, and states plainly which gates stay: rule approval
        and the finalize attestation.

## What this phase is not

**It is not the model deciding what matters.** Every demotion in it is arithmetic over
verdicts a person gave. The model's confidence score is not, and must not become, a
licence to skip anybody — a model's stated confidence is not a calibrated probability,
and a bypass built on it fails hardest exactly where it is most sure. Confidence is used
today to **discard** a weak answer and never to **trust** a strong one; that stays.

**It is not the removal of human sign-off.** A delivery is still finalized by a named
person against an attestation (Phase 6.11). What shrinks is how many things they must
read before they can honestly sign — not whether they sign.

**It is not irreversible.** Every level can be dropped, instantly, by anyone with the
console. The tool can revoke its own trust and can never grant it.

## Decisions taken

Answered by the user on 2026-09-20, before 6.18a was built. Recorded here so they are
not relitigated; the ones 6.18a acted on are in ADR-043.

| Question | Answer |
| --- | --- |
| How many maturity levels | **Three** — training, supervised, trusted. The middle one is where the evidence for the final step is collected, so a customer never jumps from *see everything* straight to *see almost nothing*. |
| What trust attaches to | **Customer plus programme.** Faster to mature than per-configuration, and it respects the boundary where a control genuinely is implemented differently. |
| What 6.18a does on day one | **Shadow.** Compute, record, show nobody. The first evidence about whether demotion is safe must not be a reviewer failing to see something. |
| Minimum evidence to demote | **Ten occurrences, every one waved through.** A count with no exceptions, not a rate. Settable upward. |
| Signature granularity | **Include what it fired on.** Two columns, two signatures, however much they share a rule. |
| Does a demotion ever lapse | **Never on its own.** A person restores it, or a new verdict upholding the finding un-demotes it immediately. |
| Where a signature lives | Its own table, `finding_signatures` — a check and a learned rule both produce findings and both need the same history. |

## Still open

- [ ] **What is the minimum evidence for a maturity *promotion*** — deliveries,
      findings, or both? Distinct from the ten-dismissal bar above, which governs one
      signature; this governs a whole configuration moving up a level. It wants a
      number the delivery team recognizes rather than one invented here, and 6.18a's
      shadow report is what will suggest it.
- [ ] **What the sample rate should be** (6.18e). Two per cent is the instinct and
      nothing has tested it.
- [ ] **Whether promotion — findings people keep escalating getting louder — belongs in
      6.18b or later.** It changes what a reviewer sees and has no safe shadow form.

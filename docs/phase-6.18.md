# Phase 6.18 — Trust that is earned, measured, and revocable

**Status:** ⬜ **not started** — specified 2026-09-20 from the product goal the user
stated directly: *a reviewer should not have to look at every validation point; as the
tool learns, they should see only the real ones.*

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

## Scope · ⬜ not started

### 6.18a — Findings that learn their own severity · ⬜ not started

The single highest-value item, and it needs no new data — only for something to read the
counters that already exist.

- [ ] A **finding signature**: the stable identity of "this same finding again" —
      rule or check reference, finding type, and the scope it fired in. Not the run, not
      the wording. Two findings share a signature when a reviewer would call them the
      same thing.
- [ ] A **verdict history per signature**: how many times it fired, how many times a
      person marked it OK, how many Not OK, and the decision reasons they gave.
- [ ] A signature whose history is overwhelmingly *OK* is **demoted**, not deleted: it
      drops out of the review queue and onto an "also checked" list on the same screen.
      A reviewer can open that list at any time; it is one click away, never gone.
- [ ] A signature whose history is overwhelmingly *Not OK* is **promoted**, and this
      matters as much: the tool should get louder about what people keep escalating.
- [ ] Demotion and promotion are **computed by code from the counts** (ADR-001). The
      model is not asked whether a finding is important.
- [ ] Every demotion records **which runs' verdicts justified it**, so the decision can
      be shown to an auditor as evidence rather than asserted as a policy.

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

### 6.18f — The first worked instance: the programme check · ⬜ not started

Phase 6.17a measured the programme keyword check and found it brittle. Its deterministic
repair lands in 6.17a. The *learning* half belongs here, and it is the smallest complete
example of the whole phase.

- [ ] When the keyword check flags a delivery and a reviewer answers *"no, this is
      Account Solicitation — we call it a promotional acquisition campaign"*, that phrase
      is offered to an administrator as an addition to the programme's word list.
- [ ] Approved, it becomes an ordinary keyword. **The next run matches it in code** —
      no model, no flag, nobody asked. The tool stopped asking because it now knows.
- [ ] Where the words still miss, the model is consulted **once**, after the code check
      has failed, and is asked *which programme does this read like, and which words say
      so* — never *is this the right programme*, which is a comparison and is code's
      (ADR-001). This is 6.15 option A's shape, applied to a second surface.
- [ ] The model's answer never silently clears the flag. Code compares it to what was
      declared and decides the severity, exactly as the compliance locator does.

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

## Open questions

- [ ] **Where does a signature live** — beside the rule, or in its own table? A check
      and a learned rule both produce findings, and both need the same history.
- [ ] **How many maturity levels?** Three is the instinct. Two may be enough, and fewer
      is easier to explain to a customer.
- [ ] **Does demotion follow a scope or a configuration?** A customer running the same
      programme twice probably wants one answer; two customers should not share trust.
- [ ] **What is the minimum evidence** for a promotion — deliveries, findings, or both?
      This wants a number the delivery team recognizes, not one invented here.
- [ ] **Does a demoted signature ever come back on its own** after enough time or a
      changed configuration? ADR-021's "no rule expires on its own" suggests not, but a
      configuration that changed materially is a different question.

# Phase 7.1 — The shadow evidence, gathered where it exists

**Status:** ⬜ **dormant** — like [`phase-7.md`](phase-7.md), this runs **only when the
user asks**, on the machine and the deployment that hold the real files. It is not a
prerequisite for anything, and no synthetic run substitutes for it.

Specified 2026-09-20, when Phase 6.18a shipped the machinery and it became clear the
thing it needs cannot be manufactured here.

## Why this is its own phase

[`phase-6.18.md`](phase-6.18.md) 6.18a built the part that decides which recurring
findings a reviewer has stopped needing to see. It records that decision and **acts on
none of it**: every reviewer still sees every finding. That was deliberate, because the
first evidence about whether hiding a finding is safe must not be a reviewer failing to
see something.

But the evidence it needs is **real verdicts from real people on real deliveries**, and
that is the one thing this repository cannot produce. Synthetic fixtures can prove the
arithmetic is right — they do, in `tests/training/test_demotion.py` — and they can prove
the screen fills — `scripts/seed_demo.py` does that. Neither can tell you whether ten
dismissals in a row actually means the eleventh is harmless in this business, on these
programmes, for these customers. Only the work says that.

So the machinery ships, the question ships with it, and the answer waits for the place
where it exists. **6.18b is not buildable until this has run**, and building it on a
guessed threshold would be exactly the mistake 6.18a was designed to avoid.

## Where it runs

**Stage 3 of [`gd-rollout-plan.md`](gd-rollout-plan.md)** — senior-associate validation
with Train AI mode on. That stage already puts the people who know the work best through
their normal caseload for four to six weeks, recording a verdict on every finding. Those
verdicts are the input to this phase; no extra work is asked of anybody.

Running it earlier produces nothing. Stages 1 and 2 have too few deliveries and their
reviewers are still learning the tool, so their dismissals measure unfamiliarity rather
than harmlessness.

## What to do

### 7.1a — Let it gather · ⬜ not started

- [ ] Confirm the migration has run and `finding_signatures` exists on the deployed
      database.
- [ ] Confirm **Review load** is reachable in the admin console and its banner says
      nothing is being acted on. If that banner is missing, the deployment is not
      running 6.18a and the rest of this phase is meaningless.
- [ ] Change nothing else. In particular **do not raise or lower the ten-dismissal
      bar** before there is evidence: the number is a starting point to be tested, and
      moving it first destroys the test.

### 7.1b — Ask the question · ⬜ not started

At the end of stage 3, with the seniors who produced the verdicts:

- [ ] Open **Review load** and go through the *would be hidden* list with them. The
      question is the one on the screen: **would hiding this have been safe?**
- [ ] For each row, record one of: *safe* (hiding it loses nothing), *unsafe* (a real
      issue would have been missed), or *unsure*.
- [ ] Record the answers **in writing**, with the date, the names, and the run ids the
      screen quotes. This is the evidence, and a verbal agreement is not.
- [ ] Do the same for the *blocked* list, for the opposite reason: a signature blocked
      by one escalation among many dismissals is worth understanding. If the seniors
      say that single escalation was a mistake, the blocking rule is working exactly as
      intended and they should say so; if they say the escalation was right, that is the
      strongest possible confirmation of the rule.

### 7.1c — Decide what it means · ⬜ not started

- [ ] **Any *unsafe* row is the answer**, and the answer is no. Do not build 6.18b.
      Work out what the signature has in common with the ones that were safe, and say
      so in this document. A bar that lets through one real defect is not a bar that
      needs raising; it is a rule that is wrong in kind.
- [ ] **All safe, with a reasonable sample:** record the count, and 6.18b is justified
      as specified. The evidence for the promotion bar (`phase-6.18.md` "Still open")
      comes out of the same exercise: how many deliveries did it take to reach this?
- [ ] **All safe, but only a handful of rows:** the answer is *not yet*. Say how many
      rows would be enough, and wait for stage 4.
- [ ] Record the outcome here and in an ADR, whichever way it goes. **A measurement
      that says "this is fine" is worth as much as one that says it is not** — the same
      principle Phase 6.17a was run on.

### 7.1d — What the real files may change · ⬜ not started

Things that cannot be known until real artifacts are in front of the tool, and that
affect what this phase measures:

- [ ] **Whether `element_ref` is populated the way signatures assume.** A signature is
      per customer, per programme, per rule, and per *the thing it fired on*. If real
      findings leave `element_ref` empty, every finding from one rule collapses into a
      single signature and the granularity the design chose is not there. Check this
      first, on real findings, before reading anything else on the screen.
- [ ] **Whether customer names are written consistently.** The signature folds case and
      trims space; it does nothing about *Acme Corp* versus *Acme Corporation*, which
      would split one customer's evidence in two and make the bar unreachable.
- [ ] **Whether the programme is set on real runs.** A run submitted without one gets an
      empty scope, and every such run shares a scope with every other. That is safe —
      it only pools evidence more coarsely than intended — but it should be known
      rather than discovered.

## Its one hard rule

The same as Phase 7's, and it is not negotiable: **no real customer file, and nothing
derived from one, enters this repository** (ADR-003, ADR-019). What comes back from this
phase is counts, dates, verdicts and decisions — never a finding's text, never a
customer's data, never a screenshot of either.

## What this phase is not

**It is not a re-run of the benchmark.** The stage 2 and stage 3 benchmarks measure
whether the tool's findings are right. This measures whether a *particular finding that
was right to raise the first ten times* is right to keep raising. Different question,
different evidence.

**It is not permission to switch demotion on.** Nothing in 6.18a can be switched on;
there is no switch. What this phase produces is the evidence that justifies *building*
6.18b, which is where a switch would first exist and where it would be an
administrator's to set.

# Phase 6.5 — Training documentation, kept current

**Status:** 🟡 **in progress** — recurring by design. Started 2026-09-19 at the
user's request. This phase is never "complete" the way the others are: it is
re-entered after every major milestone, and its boxes below are reset at each
revisit.

**Goal:** two documents that teach the tool as it actually is: `user-training.md`
for the associates who validate deliveries, and `admin-training.md` for whoever
operates it. Both are checked against the product on a schedule rather than when
someone remembers.

## The rule

**A training document that describes a screen the product no longer has is worse
than no document**, because the reader trusts it. So:

- Both documents are **re-read against the running product after every major
  milestone** — a phase closing, a screen added or removed, a workflow changed — and
  corrected in the same change.
- `CLAUDE.md` asks for a lighter check **roughly every ten commits**: open both
  documents, grep for any screen, button, or setting the recent commits renamed or
  removed, and fix what is stale. The check is cheap; skipping it is how the
  documents rot.
- Each document carries a **"Last aligned with the code"** date at its head. A date
  more than one milestone old is itself a finding.

## Scope, reset at each revisit

Last revisit: 2026-09-19, after Phase 6.4.

- [x] `docs/user-training.md` written against the product as it stands: sign-in,
      the sidebar and the Train AI indicator, submitting a run with parts, delivery
      context and configuration notes, reviewing, the frozen report, config history,
      Train AI mode, and the refusals a user will meet.
- [x] `docs/admin-training.md` written against the product as it stands: accounts,
      artifact types and samples, programmes, checks, the training queue and
      candidates, the Rules screen and its typed confirmations, Settings with its
      sources, reference data, usage, and a weekly routine.
- [x] Both referenced from `README.md`, `CLAUDE.md`, and the rollout plan.
- [ ] Both re-read after the next milestone and their alignment dates moved.
- [ ] A short walkthrough recorded for each, once the deployment the training will run
      on exists (Stage 1 of `rollout-plan.md`).

## Acceptance criteria, re-checked at each revisit

1. [x] Every screen, control, and setting named in either document exists in the
   product, under that name.
2. [x] Every refusal message quoted in `user-training.md` is one the API actually
   returns.
3. [ ] A new associate can submit, review, and finalize a run using only
   `user-training.md`; a new administrator can work the queue and activate a rule
   using only `admin-training.md`. Verified with a real person at Stage 2 of the
   rollout.

# vigilAI — Global delivery rollout plan

**Owner:** the delivery lead. **Referenced from:** `CLAUDE.md`. **Status:** plan;
dates are filled in when the first UAT cohort is named. Revisit at every milestone in
`docs/phase-plan.md`.

The tool replaces a check done by eye with one done by a model that reads and code
that compares. A rollout of that kind fails in two known ways: people do not trust
the findings, or the rules the tool ships with do not match how the teams actually
work. Both are addressed by putting the people who do the work in front of the tool
early, in a mode where what they know becomes rules, before anyone is asked to rely on
it.

## The shape of the rollout

Four stages, each with an exit gate. Nothing moves to the next stage on a date; it
moves when the gate is met.

```
1. Readiness  →  2. Focus-group UAT  →  3. Senior-associate validation  →  4. General rollout
   (platform)      (does it work?)         (are the rules right?)             (region by region)
```

### Stage 1 — Readiness

The platform team, with the administrator.

- [ ] Deployed on the internal network over TLS, with `docker compose up --build`
      verified on the target host (the last unverified criterion in phases 0–5).
- [ ] Postgres, not SQLite, behind `DATABASE_URL`; the data volume on encrypted
      storage; backups of the database, the data volume, and `VIGILAI_SECRET_KEY`
      tested by restoring them once.
- [ ] Login on for both apps, the bootstrap password changed, two administrators
      created, and every UAT participant given an account.
- [ ] The in-house model gateway set in Settings and **Test connection** green.
      The golden set run against it with `scripts/golden_set.py` and the numbers
      recorded in `docs/benchmarks/`. A prompt-version bump if they call for it.
- [ ] Artifact types matched to the real report layouts (Phase 7, on the machine that
      holds the real files), with a sample stored for each and named values resolving
      on every sample.
- [ ] Masked columns populated from the real DIRT layout. The PII tripwire on.
- [ ] Retention agreed and recorded as an ADR; security and compliance sign-off on
      retention and PII handling recorded as an ADR.
- [ ] Throughput limits set for the expected load, and the load test run once at that
      load.
- [ ] `docs/user-training.md` and `docs/admin-training.md` re-read against the
      deployed version and corrected.

**Gate:** an administrator submits one real order end to end, reviews it, and
generates its report, with nothing edited by hand along the way.

### Stage 2 — Focus-group UAT

A focus group of six to ten associates across the three programmes, plus one
administrator. Two to three weeks. **Train AI mode off**: this stage asks whether the
tool works, not whether its rules are right.

- [ ] A UAT script per programme: five real orders each, chosen to include one clean
      delivery, one with a known defect, and one that was hard to check by eye.
- [ ] Each participant runs their orders, reviews every finding, and generates the
      report. They record, per finding: agree, disagree, or unsure, and why.
- [ ] **Benchmark.** For each order, the tool's findings against the outcome of the
      manual check that was actually done at the time. Record precision (findings
      that were real) and recall (real defects the tool found), per programme and per
      finding type. These numbers are the baseline every later change is measured
      against; keep them in `docs/benchmarks/`.
- [ ] Time to review per order, against the time the manual check took.
- [ ] Every "disagree" and "unsure" triaged by the administrator into: a wrong
      extraction (prompt work), a missing alias or masked column (reference data),
      a missing or wrong rule (goes to stage 3), or a defect (fix before stage 3).
- [ ] Usability notes collected in one place and the top five fixed.

**Gate:** precision above the agreed floor on every programme, no open defect that
blocks a review, and the focus group willing to say so in writing.

### Stage 3 — Senior-associate validation, Train AI mode on

The people who know the work best, validating real orders with the mode on, so the
rules get defined by them rather than guessed by us. Four to six weeks, or until the
queue goes quiet.

- [ ] Four to eight senior associates, at least one per programme, each validating
      their normal caseload through the tool alongside the existing manual check for
      the first two weeks.
- [ ] **Train AI mode on.** Every disagreement with a finding, every check they make
      by habit that the tool did not make, and every configuration with special rules
      is recorded as an observation or a configuration note, anchored to what they
      were looking at.
- [ ] The administrator works the queue **twice a week**: rejects with reasons,
      synthesizes the rest, replays every candidate, and approves into shadow.
- [ ] Shadow rules reviewed weekly with their fired and dismissal counts. Activate
      the ones that earn it; narrow the ones that fire on the wrong population.
- [ ] Standing instructions written for each programme from what the seniors say is
      always true of it, and artifact guidance written for each report type from
      what they say they look at.
- [ ] The benchmark from stage 2 re-run at the end, on the same orders, with the
      learned rules active. The difference is the value of this stage.
- [ ] Every senior signs off that the rules for their programme reflect how they
      check, and lists what is still missing.

**Gate:** the queue has gone quiet, meaning a week with fewer than a handful of new
observations; the re-run benchmark is at or above stage 2 on every programme; and the
seniors have signed off.

### Stage 4 — General rollout

Region by region, or team by team, never all at once, so the first group's questions
become the second group's training.

- [ ] Training sessions from `docs/user-training.md`, delivered by the seniors from
      stage 3 rather than by the platform team. An hour, with each attendee submitting
      one order in the session.
- [ ] A named administrator per region, trained from `docs/admin-training.md`, with
      the weekly routine at its foot on their calendar.
- [ ] For each group, two weeks running the tool alongside the manual check, then the
      manual check retired for that group when its precision matches stage 3.
- [ ] Train AI mode stays on. New observations keep arriving from each group and the
      administrator keeps working the queue; that is how the tool keeps fitting the
      work as it changes.
- [ ] A monthly review for the first quarter: the benchmark numbers, the rules
      activated and disabled, the dismissal rates, and the throughput and queue-wait
      numbers from the usage screen.

**Gate:** every group live, the manual check retired, and the monthly review showing
precision holding or improving.

## Roles

| Role | Does |
| --- | --- |
| Delivery lead | Owns this plan and the gates; names the cohorts. |
| Administrator | Operates the tool; works the training queue; owns the rules. |
| Platform team | Stage 1; TLS, storage, backups, the model gateway. |
| Focus group | Stage 2; runs the UAT script; records agree, disagree, unsure. |
| Senior associates | Stage 3; validate with the mode on; sign off the rules; deliver stage 4 training. |
| Security and compliance | The two ADRs in stage 1. |

## What is measured throughout

- **Precision and recall per programme and per finding type**, from the benchmark,
  re-run at each stage on the same orders.
- **Time to review per order**, against the manual check.
- **Dismissal rate per rule**, from the Rules screen. The signal for a rule that is
  under-scoped.
- **Queue wait and runs per day**, from the usage screen, against the throughput
  limits.
- **Observations per week**, which should rise in stage 3 and settle in stage 4.

## Risks this plan is built around

- **Trust.** Addressed by stage 2's benchmark against the manual check, and by every
  finding carrying its evidence from all three artefacts.
- **Rules that do not match the work.** Addressed by stage 3: the seniors define them,
  and shadow mode keeps a new rule from interrupting anyone until its precision is
  known.
- **Personal data.** Masked columns and the tripwire from stage 1; the refusal to save
  an observation that looks like it carries any.
- **Losing what people taught it.** Nothing in the training record is ever deleted,
  and the master key and database are backed up in stage 1.

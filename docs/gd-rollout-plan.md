# Greenlight AI — Global Delivery rollout plan

**Owner:** the product owner, named in section 2. **Referenced from:** `CLAUDE.md`.
**Status:** plan; names and dates are filled in at the intake meeting (section 9).
Revisit at every milestone in `docs/phase-plan.md`.

This is the **delivery** document, not the engineering one. It says how the tool
reaches the Global Delivery teams and how it is owned, supported, and accepted once it
has: who decides, who is called when it fails, where a user goes with a question, who
patches it, who adds to it, and what has to be true before a team is allowed to rely
on it. Engineering readiness lives in `deployment.md`; the phases live in
`phase-plan.md`.

## Contents

1. The shape of the rollout
2. Ownership and the operating model
3. Support: where a user goes, and what happens when it fails
4. Escalation
5. Change: patching, features, and releases
6. The acceptance process
7. Training and communication
8. What is measured
9. The intake questionnaire: questions to answer before stage 1
10. Roles and RACI
11. Risks

---

## 1. The shape of the rollout

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
      storage; backups of the database, the data volume, and `GREENLIGHT_AI_SECRET_KEY`
      tested by restoring them once.
- [ ] Login on for both apps, the bootstrap password changed, two administrators
      created, and every UAT participant given an account.
- [ ] The in-house model gateway set in Settings and **Test connection** green.
      The golden set run against it with `scripts/golden_set.py` and the numbers
      recorded in `docs/benchmarks/`. A prompt-version bump if they call for it.
- [ ] Artifact types matched to the real report layouts (Phase 7, on the machine that
      holds the real files), with a sample stored for each and named values resolving
      on every sample.
      Then **Meaning** run on the real samples: Map each programme, confirm the
      mappings, and let the compiled checks run in shadow through UAT (Phase 6.10);
      a validation guide per report type for the cells that need it (Phase 6.8).
- [ ] Phase 6.11 landed before UAT: the bulk-OK defect fixed, the finalize gate
      fail-closed with the attestation, coverage on the review screen and the report,
      and the benchmark harness reporting precision and recall per finding type.
      Stage 2's benchmark is that harness run against the manual check.
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


## 9. The intake questionnaire: questions to answer before stage 1

Answered in one meeting with the product owner, the technical owner, the delivery
lead, and one senior per programme. Recorded at the foot of this document. A question
without an answer is a risk with a name.

**Ownership**
1. Who is the product owner, and do they have the authority to stop a rollout?
2. Who is the technical owner, and is the tool in their on-call rotation?
3. Who is the administrator for each region, and who covers their absence?

**Scope and sequence**
4. Which programme and region go first, and why that one?
5. Which orders are in the UAT script, and were their manual outcomes recorded well
   enough to benchmark against?
6. What precision and recall floor is acceptable before a team relies on the tool,
   and who set it?
7. Is anything out of scope for the tool that a user might expect it to check?

**Support and failure**
8. Where does a user go with a question, by name and channel?
9. What does a team do for a shift when the tool is down?
10. What is the response time for an S1 at 02:00 in that region?
11. Who is told when a delivery went out that the tool passed and should not have?

**Change**
12. Who may change settings and rules in production, and is that audited?
13. Who patches, on what rhythm, and who approves a hotfix?
14. Who ranks feature requests, and how does a user submit one?
15. What is the release rhythm, and which region takes a release first?

**Data and compliance**
16. What is the retention period, who approved it, and is it an ADR?
17. Has security and compliance signed off on masked columns and the tripwire?
18. Where do the database, the data volume, and the master key get backed up, and
    when was a restore last tested?
19. Is the model gateway in-house, and has anyone confirmed what it logs?

**People**
20. Who are the senior associates for stage 3, and is their time protected?
21. Who delivers the training, and when is the first session?
22. What is the plan for the person who refuses to use it?

**Acceptance**
23. Who signs the acceptance for each scope?
24. What would make the product owner stop the rollout, in one sentence?

### Answers

| # | Answer | Date |
| --- | --- | --- |
| 1 | | |

## 10. Roles and RACI

| Role | Does |
| --- | --- |
| Product owner | Owns this plan and the gates; ranks the backlog; signs acceptance. |
| Technical owner | Owns the build, releases, patching, and tier 3. |
| Delivery lead | Names the cohorts; decides remediation with the product owner; signs acceptance for their region. |
| Administrator | Operates the tool; tier 2; works the training queue; owns the rules. |
| Platform team | Stage 1; TLS, storage, backups, the model gateway. |
| Focus group | Stage 2; runs the UAT script; records agree, disagree, unsure. |
| Senior associates | Stage 3; tier 1; validate with the mode on; sign off the rules; deliver stage 4 training. |
| Security and compliance | The two ADRs in stage 1; consulted on any S1 with a data angle. |

**RACI** (R responsible, A accountable, C consulted, I informed):

| Activity | Product owner | Technical owner | Delivery lead | Administrator | Seniors | Platform | Security |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Stage 1 readiness | A | R | I | C | I | R | C |
| UAT script and benchmark floor | A | C | R | C | C | | |
| Running UAT | A | I | R | C | R | | |
| Triage of disagreements | I | C | I | R | C | | |
| Rules and settings in production | I | I | I | A/R | C | | |
| Learned rules: synthesize, approve, activate | I | | | A/R | C | | |
| Patching | I | A | | I | | R | C |
| Features and releases | A | R | I | C | C | | |
| S1 response | I | A/R | I | R | | R | C |
| Acceptance signature | A/R | C | R | C | R | | I |
| Training delivery | A | C | I | R | R | | |


## 2. Ownership and the operating model

A tool with no owner is a tool nobody is allowed to change and nobody is obliged to
fix. Three owners, named at intake, each with one sentence of authority.

| Owner | Authority | Named at intake |
| --- | --- | --- |
| **Product owner** (Global Delivery) | Decides what the tool should do: priorities, feature requests, the acceptance gates, and whether a team goes live. Owns this plan. | ☐ |
| **Technical owner** (engineering) | Decides how it is built and run: the release process, patching, the model, the backlog's technical shape. Owns `deployment.md` and the repo. | ☐ |
| **Administrator** (one per region) | Operates it day to day: accounts, settings, the training queue, the rules. Owns the weekly routine in `admin-training.md`. | ☐ |

**Decision rights that come up in practice:**

- A user disagrees with a rule → the regional administrator, who narrows or disables
  it and tells the product owner if it is systemic.
- A team wants a new report type or check → the administrator can do it from the
  console; if it needs code, the product owner ranks it and the technical owner
  schedules it.
- The tool is wrong in a way that affects a delivery already sent → the product owner
  decides on remediation with the delivery lead; the technical owner fixes the cause.
- Whether to turn Train AI mode on or off for a region → the regional administrator,
  with the product owner informed.
- Whether to retire the manual check for a team → the product owner, on the
  numbers in section 8, never on a date.

**Cadence:** a fortnightly product meeting (product owner, technical owner, one
administrator per region, one senior associate per programme) that reads the numbers
in section 8, ranks the backlog, and records decisions in `docs/decisions.md` when
they change the product's shape.

## 3. Support: where a user goes, and what happens when it fails

Three tiers. Each has a named channel, a response time, and a list of what it handles
so a question is not bounced.

| Tier | Who | Channel | Responds within | Handles |
| --- | --- | --- | --- | --- |
| **Tier 1 — the floor** | The senior associates from stage 3, one per programme per region | The team channel; in person | Same shift | "How do I…", a finding someone does not understand, a rule that seems wrong, a report type they cannot find |
| **Tier 2 — the administrator** | The regional administrator | A named support queue or mailbox, with the run id | Next business day | Accounts and access, settings, a rule to narrow or disable, an observation to promote, a sample to add, a run that failed with a message the user cannot act on |
| **Tier 3 — engineering** | The technical owner's team | The issue tracker, raised only by an administrator | By severity, section 4 | A defect, a run that fails without a usable message, the model gateway down, data corruption, a security concern |

**Rules that keep the tiers working:**

- A user never goes to tier 3 directly. Tier 2 raises it, with the run id, the stage
  it failed at, and what the audit log shows.
- **Every run carries its own diagnosis.** A failed run shows its stage and error on
  the run page; the audit log shows who did what; the Rules screen says what made a
  finding fire. Tier 1 and 2 use these before raising anything.
- **No personal data in a ticket.** Run ids, stage names, counts, and the finding's
  title. Never a row, never a value from a report. The same rule the tool itself
  keeps (ADR-003).
- A question that arrives three times becomes a line in `user-training.md`.

**When the tool is down or wrong, what the teams do:**

| Situation | What happens |
| --- | --- |
| The tool is unreachable | The team falls back to the manual check for that shift. Tier 2 raises to tier 3 as **S1**. The product owner is told within the hour. |
| A run fails | The user reads the stage and message on the run page. If it is an input problem (a file the parser cannot read, a missing report), they fix and resubmit. Otherwise tier 2. |
| A finding is wrong | The user marks it OK with a comment saying why, which is the record. If it will keep happening, they raise an observation (Train AI mode) or tell tier 1, who tells tier 2 to narrow the rule. |
| The model gateway is down | Runs queue and wait; nothing is lost. Tier 3 restores the gateway; queued runs then complete. Users are told the expected time. |
| A delivery went out that the tool passed and should not have | The product owner and delivery lead decide remediation. Tier 3 finds the cause. The case becomes an observation and a rule, and a benchmark case. |

## 4. Escalation

Severity is decided by tier 2 when raising, and may be raised by tier 3.

| Severity | Definition | Acknowledge | Update every | Resolve or work around | Who is told |
| --- | --- | --- | --- | --- | --- |
| **S1** | Nobody in a region can validate; or a suspected data or security exposure | 30 minutes | 2 hours | 8 hours | Product owner, technical owner, delivery lead, immediately |
| **S2** | A programme or a report type cannot be validated; findings systematically wrong | 4 hours | Daily | 3 business days | Product owner, technical owner |
| **S3** | A single run or a single rule; a usability problem with a workaround | Next business day | Weekly | Next release | Administrator |
| **S4** | A request, a question, cosmetic | Weekly | — | Backlog | Product meeting |

An S1 that is not acknowledged in time goes from the administrator to the technical
owner directly, then to the product owner. Every S1 and S2 gets a written post-mortem
within a week: what happened, what the tool showed, what it should have shown, and
what changed. Post-mortems live with the ADRs.

## 5. Change: patching, features, and releases

| Kind of change | Who does it | Who approves | How it reaches users |
| --- | --- | --- | --- |
| **Settings, rules, samples, artifact types, programmes** | The regional administrator, from the console | Nobody; audited, revertable, effective at once | Immediately. Users see a switched-off type disappear on the next form. |
| **Learned rules** | The administrator, through the training queue | The administrator approves; a person always | Shadow first, then active with the numbers in view |
| **Security patches** to dependencies, the base images, the OS | The technical owner's team | The technical owner | Monthly at least; within a week for a published critical. A patch never changes behaviour; if it must, it is a release. |
| **Bug fixes** | Engineering | The technical owner; the product owner if behaviour changes | The next release, or a hotfix for S1/S2 |
| **Features** | Engineering, from the ranked backlog | The product owner ranks; the technical owner schedules | A release, announced a week ahead, with the training documents updated in the same release (`phase-6.5.md`) |
| **Model or prompt changes** | Engineering | The technical owner, after the golden set is re-run and its numbers recorded | A release. The cache key changes with the prompt version, so the next run of every order re-asks; users are told to expect slower first runs. |
| **Real-file fit** (parser changes) | Engineering, on the in-house machine (Phase 7) | The technical owner | A release, with a synthetic fixture for the new shape |

**Release rhythm:** a release every four to six weeks during rollout, monthly after.
Every release: the gates in `standards/git.md`, the golden set re-run, both training
documents re-aligned, a one-page release note to the administrators, and a
rollback tested once on a staging copy before it reaches production. A release goes to
one region first for a week.

**What never changes without the product owner:** the hard rules in `CLAUDE.md`, the
finalize gate, retention, and what the model is allowed to see.

## 6. The acceptance process

Global Delivery accepts the tool for a scope, one programme in one region at a time,
against written criteria. Acceptance is a signature, not a feeling.

**Entry criteria** (before UAT starts for that scope): stage 1 complete; the UAT
script written and agreed; the cohort named and trained; the benchmark method agreed,
including the floor for precision and recall; a rollback to the manual check written
down.

**During UAT:** every session logged with the run ids; every disagreement triaged
within two days; a defect list with severities, reviewed at the end of each week; no
scope change without the product owner.

**Exit criteria** (to sign the acceptance for that scope):

- [ ] The benchmark meets the floor for precision and recall on that programme, on
      real orders, against the manual check that was actually done.
- [ ] No open S1 or S2. Every S3 has a workaround the users have accepted.
- [ ] Time to review per order at or under the manual check.
- [ ] The cohort has finalized reports the delivery lead would have signed.
- [ ] Support tiers staffed and the escalation path tested with one dry-run S2.
- [ ] Training delivered; the two training documents match the deployed version.
- [ ] Retention and PII sign-off in hand as ADRs.
- [ ] The product owner, the delivery lead for that region, and one senior associate
      for that programme sign. The signature names the scope and the date.

**After acceptance:** a thirty-day hypercare period for that scope with tier 2
response times halved and the product meeting weekly, then business as usual.

## 7. Training and communication

- **Users** are trained from `user-training.md` by the senior associates, an hour with
  one order submitted live. Refresher at each release that changes a screen.
- **Administrators** are trained from `admin-training.md` by the technical owner, half
  a day, ending with the trainee working a seeded training queue and activating a
  shadow rule.
- **Announcements**: a week before a release, from the product owner, saying what
  changes for users; the day of, from the administrator, saying it is live.
- **A single page** users can reach from the tool's sidebar, or pinned in the team
  channel, with: the tier 1 names for their programme, the tier 2 mailbox, the current
  version, and the last release note.

## 8. What is measured

- **Precision and recall per programme and per finding type**, from the benchmark,
  re-run at each stage on the same orders.
- **Time to review per order**, against the manual check.
- **Dismissal rate per rule**, from the Rules screen. The signal for a rule that is
  under-scoped.
- **Queue wait and runs per day**, from the usage screen, against the throughput
  limits.
- **Observations per week**, which should rise in stage 3 and settle in stage 4.

## 11. Risks this plan is built around

- **Trust.** Addressed by stage 2's benchmark against the manual check, and by every
  finding carrying its evidence from all three artefacts.
- **Rules that do not match the work.** Addressed by stage 3: the seniors define them,
  and shadow mode keeps a new rule from interrupting anyone until its precision is
  known.
- **Personal data.** Masked columns and the tripwire from stage 1; the refusal to save
  an observation that looks like it carries any.
- **Losing what people taught it.** Nothing in the training record is ever deleted,
  and the master key and database are backed up in stage 1.

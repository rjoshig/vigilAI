# Greenlight AI — Design brief for presentations and documents

**Purpose of this file.** A self-contained description of what Greenlight AI is, how it
works, why it was built the way it was, and what it changes for the people who use
it. Written to be pasted into a chat or a document tool to produce slide decks,
design documents, and management briefings. Everything here is at the level a user or
a manager needs; engineering detail lives in the repository. Diagrams are in Mermaid
so they render in most tools and can be redrawn in any.

**As of:** 2026-09-20. The tool is **built through phase 6.18a and 6.18f** and is ahead
of its first UAT: the pipeline, both apps, the frozen report, the learning loop, and the
machinery that will let a reviewer stop reading every finding. It has been run end to end
against a real commercial model, not only the scripted stand-in. Timing figures in
sections 10 and 11 are expected values to be confirmed in UAT, not measurements — and
where a number *has* been measured, this document says so and says what it was measured
on.

---

## 1. The problem, in one paragraph

Every credit-data delivery is checked by a person before it goes to the customer.
The check reconciles three things: what the customer asked for (the **OSL**, a Word
document called the Order Specification Letter), what the extract was configured to
do (the **ETL configuration**, a JSON file from the Solution Canvas), and what
actually came out (the **reports**, Excel workbooks: a data-integrity report called
the DIRT, field and state distributions, counts, billing). Today an associate reads
all three, holds them in their head, and looks for disagreements. It takes about three
to six hours per order, it depends on who is doing it, and a miss reaches the
customer.

## 2. What Greenlight AI does

It reads the OSL, works out what it requires, traces every requirement into the
configuration and then into the reports, and shows the associate a list of
**findings**: the places where the three disagree. The associate decides each finding,
OK or Not OK, and the tool produces a frozen one-page report with a PDF. The judgement
stays with the person; the reading and the comparing move to the tool.

```mermaid
flowchart LR
    OSL[OSL<br/>what the customer asked for] --> V((Greenlight AI))
    CFG[ETL configuration<br/>what the extract was set to do] --> V
    REP[Output reports<br/>what actually came out] --> V
    V --> F[Findings<br/>where the three disagree]
    F --> A[Associate decides<br/>OK / Not OK]
    A --> R[Frozen one-page report<br/>+ PDF]
```

## 3. The one design rule that everything else follows

**The model reads and judges meaning. Code does every comparison.**

A language model is good at reading a sentence like "deliver only accounts in the
following states" and understanding that it is a geography requirement. It is not
reliable at comparing two lists, adding counts, or checking that 755 is above 750. So
the tool never asks it to. The model extracts what a document means into structured
data; deterministic code compares the data. The result is that every finding is
exact, repeatable, and explainable: the same inputs always produce the same findings,
and each finding shows the evidence from all three artefacts side by side.

```mermaid
flowchart TB
    subgraph Model["The model: reads and judges meaning"]
        M1[Extract what each OSL section requires]
        M2[Describe what each configuration block does]
        M3[Judge whether a configuration block implements a requirement]
        M4[Write the plain-language summary]
    end
    subgraph Code["Code: does every comparison"]
        C1[Compare values, sets, ranges, operators]
        C2[Reconcile counts across reports]
        C3[Check reports against requirements]
        C4[Run the administrator's rules]
    end
    Model --> Code
    Code --> F[Findings with evidence]
```

**Why this matters to a manager:** the tool's answers are auditable. A finding is not
"the AI thinks something is wrong"; it is "the OSL says X, the configuration says Y,
the report shows Z, and here are the three cells". That is what makes it usable for
sign-off.

## 4. How a run works

Nine stages, run by a background worker after the associate submits. The associate
does nothing until the run reaches **Needs review**.

```mermaid
flowchart LR
    S1[1 Parse<br/>the three files] --> S2[2 Extract<br/>requirements from the OSL]
    S2 --> S3[3 Describe<br/>the configuration]
    S3 --> S4[4 Trace<br/>requirement to config]
    S4 --> S5[5 Compare<br/>values, code only]
    S5 --> S6[6 Reverse pass<br/>config not in the OSL]
    S6 --> S7[7 Check reports<br/>against requirements and rules]
    S7 --> S8[8 Verify<br/>each finding once more]
    S8 --> S9[9 Summarise]
    S9 --> NR([Needs review])
```

What the stages catch, in plain terms:

| Stage | Catches |
| --- | --- |
| Trace and compare | A requirement in the OSL that the configuration does not implement, or implements with a different value or operator. |
| Reverse pass | Something in the configuration the OSL never asked for: an extra filter, an extra state. |
| Check reports | A report that does not satisfy a requirement: a state that should not be there, counts that do not reconcile down the waterfall, a billing figure above the delivered figure. |
| Verify | A second look at each finding, so a shaky extraction is flagged for review rather than presented as fact. |

## 5. What the associate sees

```mermaid
flowchart TD
    N[New run: fill the form,<br/>drop the files, submit] --> Q[Queued, then running:<br/>progress shown live]
    Q --> RV[Review: findings worst first,<br/>evidence from all three artefacts]
    RV --> D{Decide each finding}
    D -->|OK| RV
    D -->|Not OK + comment| RV
    RV --> G{Every high-severity<br/>finding decided?}
    G -->|no| RV
    G -->|yes| GEN[Generate report:<br/>frozen, one page, PDF]
```

Three details that shape the experience:

- **The report is frozen.** Generated once, stored, never regenerated. What was signed
  off is what stays on record.
- **High-severity findings cannot be bulk-decided.** Each one is a deliberate click.
  Low-severity ones can be.
- **The same inputs are never run twice by accident.** The tool hashes every file; if
  an identical set was already run, it shows that run and asks for a reason.
- **The artifacts are checked against the form before anything is validated.** An ETL
  configuration declares its own configuration number and the customer it was built
  for. If either disagrees with what was typed, the run stops before a single question
  is put to the model, shows both values side by side, and waits. One sentence saying
  why — four common reasons are a single click — and it runs. Nothing is re-uploaded,
  and the waiver is kept and printed on the final report, so whoever signs it can see
  that the question was asked and who answered it.

## 6. How it gets better: Train AI mode

The rules a tool ships with never match how a team actually works. So the people who
know the work teach it, with a person at every gate.

```mermaid
flowchart LR
    O[Associate records what they know,<br/>anchored to the cell or clause] --> Q[Administrator's queue]
    Q --> S[Model drafts a rule<br/>from the sentences]
    S --> V[Code validates it and<br/>checks for overlap with existing rules]
    V --> RP[Replay against past runs:<br/>what would this have changed?]
    RP --> AP{Administrator approves?}
    AP -->|no, with a reason| O
    AP -->|yes| SH[Shadow: runs silently,<br/>findings counted, shown to nobody]
    SH --> AC{Administrator activates,<br/>with the numbers in view}
    AC -->|yes| LIVE[Active: produces findings]
    LIVE --> ST[Statistics: fired, dismissed]
    ST --> AC
```

**The model does the paperwork; the specialist does the judging.** An associate writes
a sentence in their own words. From that, the model produces a short, structured brief
for the administrator to read: what it thinks the rule is, which existing rules it
would overlap, which past runs it would have fired on and what it would have changed,
and where it should apply. The specialist is not asked to write a rule or to read code.
They are asked to agree or disagree with a one-page case that the model has already
assembled — which is the difference between an expert review that takes minutes and one
that never happens.

Why it is built this way:

- **Anchored, not just written.** "This field is never blank" means nothing without
  which field. The associate clicks the cell or the clause and the note carries it.
- **Nothing activates without a person.** The model proposes; a human approves.
- **Shadow before live.** A new rule runs silently until its precision is known, so it
  cannot flood reviewers with false positives on day one.
- **Nothing is ever deleted.** What people said, what the model made of it, and who
  approved what is kept. A rule can be switched off, or deleted and restored for six
  months, but never lost.
- **Configuration notes.** A note on an ETL configuration id, written once, reaches
  the model as background on every future run of that configuration, and can be
  turned into a rule scoped to that configuration alone.


### How the associates teach it

**Training is a switch, and it is meant to be turned off.** Train AI mode is on or off,
set by an administrator from a screen. While it is off the collecting controls are not
there at all — the tool validates exactly as it does today and nothing is gathered.
While it is on, three things an associate can do become available, and every one of
them is marked so the person knows what they type is being collected.

That switch matters for the shape of the programme, not only for privacy. Teaching a
tool is front-loaded work: the first months are where the rules that matter get
written. Once a configuration is being validated to the standard the team wants,
training can simply be switched off for it, and the rules already approved keep
running. Nobody has to maintain a training effort forever to keep the accuracy that
effort bought.

- **From a finding.** Every finding on the review screen has a "What should this
  check?" control. The associate writes, in plain words, what they expected and how
  serious a miss is; the tool attaches what they were looking at, the finding and
  its cell, clause, or configuration path, so the note is anchored to a fact rather
  than floating. This is the most valuable path: a finding someone dismissed becomes
  a lesson instead of a review note nobody reads again.
- **From a run.** The same control on the run page, for something the tool did not
  check at all: "the account status column is never blank for this customer", "clause
  4.2 is what the first score band answers to".
- **Against a configuration.** A standing note on an ETL configuration id, written
  once from the new-run form or the config history. It reaches the model as
  background on every future run of that configuration, and it works whether or not
  Train AI mode is on, because it is guidance rather than training.

Each note carries how far it should apply: this customer, this programme, or
everywhere. The narrowest that fits is the default, because most false positives
come from a rule that was true of most deliveries and not all.

Nothing an associate writes runs. It goes to the administrator's queue, where the
model drafts a rule from it, code checks the draft and looks for overlap with rules
that already exist, a replay shows what it would have changed on past runs, and a
person approves it into shadow. In shadow the rule runs on every delivery and its
findings are counted but shown to nobody; the administrator activates it when the
numbers say it has earned its place. The associate sees what became of every note
they wrote, with the reason if it was turned down.

## 7. The advantages, in the order they matter

**1. It gets better at your work, not at work in general.** Every tool of this kind
ships with rules that approximate how some team somewhere operates. This one starts
with the checks the design called for and then learns the rest from the people doing
the deliveries — the exceptions, the customer-specific habits, the thing that is only
ever wrong on one programme. That knowledge currently lives in a handful of
experienced heads and leaves when they do.

**2. A specialist gates every rule, and reads a brief rather than a specification.**
Nothing an associate writes runs. The model turns their sentence into a structured
case — the proposed rule, what it overlaps, what it would have changed on past runs —
and a specialist approves, rejects with a reason, or edits it. The expert's time is
spent on the judgement only they can make, not on the transcription anyone could.

**3. A new rule cannot embarrass you on its first day.** An approved rule runs in
**shadow**: it is evaluated on every delivery, its hits are counted, and no reviewer
sees them. The administrator activates it once the numbers show what it actually
catches and how often it is wrong. This is why the team can afford to be generous
about what gets proposed.

**4. Training is a switch, and switching it off keeps what you learned.** Train AI
mode is on or off. Off, the collecting controls do not exist and the tool behaves
exactly as it always did. The rules already approved keep running. So the effort is
front-loaded: teach it until a configuration reaches the accuracy you want, then stop,
and keep the accuracy.

**5. No engineering in the loop.** This is the one that changes the economics. Adding
a report type, changing what a document means, writing a rule, scoping it to one
programme or one configuration, adjusting a threshold, retiring a check — all of it is
a screen, takes effect on the next run, and needs no code change, no release, no
deployment window and no ticket raised with a technology team. The only work that
needs engineering is work nobody has met yet: a genuinely new file format. Everything
else moves at the speed of the people who understand the deliveries.

**6. Every answer can be traced to its reason.** A finding names the clause, the
configuration path and the report cell it came from. A rule names who approved it and
from whose observation. A waived artifact mismatch names who waived it and why. The
frozen report carries all of it. Nothing in the tool asks to be trusted.

**7. The model never decides anything.** It reads and it judges meaning; every
comparison of a value, a set, a range, a count or a sequence is made by code. That is
not a limitation to be lifted later — it is what makes the results reproducible,
explainable to a regulator, and identical on two runs of the same inputs.


**8. It survives your customers writing things their own way.** The first version of
several checks matched text literally, and a measurement showed what that costs: of
twenty deliveries that were exactly what they claimed to be, worded the way a different
customer might word them, **five produced a false alarm at the highest severity the tool
has**. Singular where the rule said plural, a hyphen, two words in the other order. Those
now match, and where a customer's vocabulary is genuinely new the tool reads the
documents, recognises the work, and offers the customer's own phrase to the
administrator with one click to adopt it. The point is not that the bug was fixed — it
is that the tool was **measured for it before anybody shipped a promise**, and the
measurement is kept as a test so the answer cannot quietly change.

**9. It is honest about not knowing.** Three different checks were measured for the same
weakness and answered differently on purpose: one was repaired, one was left alone
because it already failed safely, and one was given a second opinion. A check that
cannot tell says *"could not evaluate"* rather than guessing, and a model that cannot
tell says *"unclear"* rather than picking. A tool that never says "I am not sure" is a
tool nobody can calibrate.

**10. The review list shrinks as the tool earns it — and only then.** The tool records
which recurring findings your reviewers have waved through, every time, on every
delivery. Ten occurrences with no exceptions and it marks that finding as one they have
stopped needing to see. **It then does nothing about it.** Every reviewer still sees
every finding, because the first evidence that hiding something is safe must not be a
reviewer failing to see it. What it produces instead is a list and a question — *it would
have hidden these; was any of them real?* — put to the senior people during rollout. Only
their answer justifies acting on it.

**11. Trust, when it comes, is revocable and never self-granted.** A finding judged real
even once is never hidden again. Serious findings are never hidden at any level of
evidence — the goal is a reviewer who reads only the serious ones, not one who reads
none. Nothing hidden is ever deleted: it is still evaluated, still stored, still in the
audit log, with the reason it was not surfaced. And the one automatic move in the design
runs in the safe direction only: **the tool may revoke its own trust and may never grant
it.**

## 8. Three ways to judge it: the associate, the accuracy, and the AI

The same product answers to three different audiences, and the honest answer is
different for each. A brief that gives only one of them will be challenged by whichever
room it did not address.

### The associate's view — *"what changes on Monday?"*

They fill in a short form, drop three files, and come back to a list of findings with the
evidence already next to each one. They decide OK or Not OK; the tool never decides for
them. A one-page report is generated once and frozen with their name on it.

What is different from any other tool they have been given:

- **It explains itself.** Every finding names the clause, the configuration path and the
  report cell it came from. Nothing asks to be believed.
- **Their expertise is the product, not an obstacle to it.** When they disagree with a
  finding, or check something by habit that the tool missed, they write one sentence and
  it becomes a candidate rule a specialist approves. The knowledge that currently leaves
  the team when a senior person does now stays.
- **It does not nag.** When it is unsure, it says so and asks; when a customer's wording
  keeps confusing it, the fix is a click by an administrator, not a monthly irritation.
- **It cannot lock them out.** Sign-off is theirs, and the tool refuses to freeze a
  report that has not been properly reviewed rather than letting it through quietly.

### The accuracy view — *"how do we know it is right?"*

This is the question a QC function must be able to answer about its own QC tool, and the
design answers it structurally rather than by assertion.

- **Every comparison is made by code.** Values, sets, ranges, counts and sequences are
  never compared by the model. Two runs of the same inputs give the same answer, and the
  answer can be recomputed by hand.
- **Coverage is tracked, not assumed.** Every requirement read out of the OSL is traced
  into the configuration and then into the reports, and anything left unchecked is
  reported rather than silently dropped.
- **The claims are measured, and the measurements are kept.** Precision and recall per
  finding type and per programme come from a benchmark harness, not from an impression.
  Where a weakness was suspected it was measured before it was fixed, and the measurement
  became a test — for the programme check, the compliance rules, and the named values
  alike, including the one measurement that concluded *"this is fine, leave it alone"*.
- **Sign-off is fail-closed.** A report cannot be frozen with findings undecided or
  coverage gaps unacknowledged. Freezing records an attestation of what was in force.
- **It is designed to be checked, forever.** Nothing is deleted from the training record,
  every decision carries a name and a time, and the frozen report is the record of what
  was signed.

### The AI view — *"what is the model actually doing?"*

The shortest accurate answer: **the model reads and judges meaning; code does every
comparison.** That single rule explains most of the design, and it is worth being
specific about what it does and does not permit.

**What the model does.** It reads the OSL and works out what each requirement means. It
reads the configuration and describes what each block does in the same vocabulary. It
judges whether a requirement is implemented. It gives a second opinion on serious
findings — or three independent ones, merged by code. It reads a delivery for which
programme it describes when the word lists miss. It drafts a rule from a reviewer's
sentence. **All of that is reading and judging, which is what a language model is good
at.**

**What the model never does.** It never compares two values. It never counts. It never
decides whether a delivery is compliant, or whether a finding is important, or whether a
reviewer was right. It never activates anything. Its stated confidence is used to
**discard** a weak answer and never to **trust** a strong one — because a model's
confidence is not a calibrated probability, and a system that lets a model skip a human
by being sure fails hardest exactly where it is most sure.

**How the model is kept honest.** Where a model call could downgrade a serious finding,
code bounds it: the answer must quote something the model was actually offered, clear a
confidence floor, and even then it buys a *question for a person* rather than a pass. The
two calls that could soften a high-severity finding — one at stage 6, one at stage 7 —
both follow that rule, and both run **only where the deterministic check already failed**,
so the ordinary delivery costs nothing.

**And the model is a setting.** Provider, endpoint and model name come from configuration.
It runs against a model inside your own network, in which case no delivery data crosses a
boundary at all. Nothing personal reaches it in any case: columns are masked as the
workbook is read, a tripwire scans every assembled prompt before it is sent, and where the
model is shown what a report looks like it is shown labels and addresses, never a row.

## 9. What an administrator controls, without engineering

Everything below changes from a screen and takes effect on the next run, with no
deployment and no restart.

| Area | What |
| --- | --- |
| Submission | Which fields the tool checks the artifacts against before a run starts, and what this delivery calls them — a credit date written "as-of date" on one customer's reports and "cycle date" on another's. |
| Inputs | The OSL (Word or PDF), the ETL configuration, and each report type in their own tabs; what each means; up to three sample layouts per type per programme; every definition kept in ten versions with revert; a switch to hide a type from every user at once. |
| Meaning | The mapping interview: the model reads the sample OSL against the sample configuration and reports and proposes, per requirement, where it answers to; an administrator confirms, and code turns the confirmed rows into checks that run in shadow first. Global, and per programme. |
| Programmes | Account Monitoring, Account Solicitation, Archives, Other: each with standing instructions, keywords, and rules of its own with a strictness the model never grades; checks and compliance rules can be scoped to one programme. |
| Rules | Every rule the tool holds, whatever its origin, searchable, with how often it fires and how often it is dismissed. Enable, disable, delete, restore. |
| Training | The queue of what associates wrote; synthesis; approval; activation. |
| Settings | The model provider and key, login rules, throughput limits, upload size, retention, the default theme and its lock. Each shows where its value came from. |
| Accounts | Users and administrators, when login is on. |

**Why this matters:** the tool fits the work as the work changes, in days rather than
release cycles, and the people who understand the deliveries are the ones shaping it.
Nothing in that table needs a developer, a release, a deployment window or a ticket to
a technology team. The dependency a tool like this usually creates — every adjustment
queued behind somebody else's sprint — is not there, which is what lets it keep pace
with customers whose requirements change faster than release cycles do.

## 10. What changes for the associate: time and effort

Today's manual check is about three to six hours per order. The expected shape with
Greenlight AI is below. These are design targets, to be confirmed by the UAT benchmark in
the rollout plan; the honest claim before UAT is the shape of the change, not the
exact numbers.

| Step | Today | With Greenlight AI | Who is busy |
| --- | --- | --- | --- |
| Gather the three files and read them | 1 hour | 3–5 minutes to fill the form and drop the files | Associate, briefly |
| Reconcile OSL, configuration, and reports | 2–5 hours, by eye | 3–5 minutes, unattended | The tool |
| Decide what is wrong and write it up | included above | 5–10 minutes reviewing findings with evidence in front of them | Associate |
| Produce the report | 15–30 minutes | Seconds; one page, frozen, with PDF | The tool |
| **Associate's time per order** | **3–6 hours** | **about 10–15 minutes** | |

The reconciliation figure is measured rather than estimated: a full run on a real
commercial model took 33 seconds end to end. Three to five minutes is the honest
allowance for a queue and a larger delivery, and the associate is not waiting on it in
any case.

```mermaid
gantt
    title Associate time per order (expected, to be confirmed in UAT)
    dateFormat X
    axisFormat %s
    section Today
    Read and gather           :a1, 0, 60
    Reconcile by eye          :a2, 60, 270
    Write up and report       :a3, 270, 300
    section With Greenlight AI
    Submit                    :b1, 0, 5
    Tool runs (unattended)    :b2, 5, 10
    Review findings           :b3, 10, 20
    Generate report           :b4, 20, 21
```

Beyond time:

- **Consistency.** Two associates checking the same order get the same findings.
- **Coverage.** Every requirement is traced, every time. A tired reader skips; code
  does not.
- **Auditability.** Every finding carries its evidence, every decision carries a
  name, and the frozen report is the record.
- **Fewer misses reaching the customer**, which is the number that matters and the
  one the UAT benchmark measures directly: findings against the manual outcome, on
  real orders.

**And a second dimension, later.** The ten to fifteen minutes above is the review of a
full findings list. As the tool learns which recurring findings a team has consistently
waved through, that list gets shorter — a mature configuration should put three findings
in front of a reviewer where a new one puts forty. **That reduction is not claimed
here**: the machinery to measure it is built and the machinery to act on it is not,
deliberately, until the senior associates have looked at what it would have hidden and
said whether any of it was real. The honest claim today is the first table. The second
dimension is a designed-for outcome with an evidence gate in front of it.

## 11. Cost, control, and not being tied to a model

The three questions a technology group and a finance owner ask, answered from the way
the tool is built rather than from a promise.

### The model is a setting, not a dependency

There is no vendor library anywhere in the code. Every call goes through one adapter
that speaks two wire formats — the OpenAI-compatible one and the Anthropic one — over
plain HTTP. **Changing model is four lines in a configuration file, or four fields in
the admin console: provider, endpoint, key, model name.** No code change, no release,
no redeploy.

What that buys, in order of how much it matters:

- **No lock-in.** The tool runs against an in-house endpoint, a commercial API, or a
  local model on a laptop. The same code, the same results format.
- **Better models, when you want them.** Model quality is improving faster than any
  roadmap here. Moving to a better one is a configuration change that takes effect on
  the next run, and the golden set says immediately whether it was an improvement.
- **Cheaper models where they suffice.** The same switch works downward. Most of the
  reading this tool does is not hard.
- **A fallback that costs nothing to hold.** If a provider has an outage or a contract
  lapses, the alternative is a configuration change, not a project.

This has been exercised, not just designed: the tool has been run end to end on a
commercial model and on a scripted stand-in used by the tests, with no code difference
between them.

### What a run costs, and the controls on it

A full validation of a real delivery measured **33 seconds and roughly five cents**:
about 30 calls, 30,000 tokens in and 2,800 out. Four mechanisms keep it there and keep
it predictable.

| Control | What it does |
| --- | --- |
| **A token budget per run** | A ceiling set in the admin console. A run that exceeds it stops and is flagged rather than quietly spending. One pathological input cannot empty a month's budget. |
| **A content-addressed cache** | Nothing is ever sent to the model twice. The cache key is a hash of exactly what was sent, so a re-run, a repeated OSL section, or two deliveries sharing a clause cost nothing the second time. In a measured re-run, 22 of 23 calls were cache hits and the run cost a fifth of a cent. |
| **Code does the bulk of the work** | Every comparison of a value, a set, a count or a sequence is Python, and two of the nine stages make no model call at all. Two more — the compliance locator and the programme reading — call the model **only where the deterministic check has already failed**, so an ordinary delivery never pays for them. The model is used where meaning has to be read, which is the small part. |
| **A ceiling on second opinions** | Stage 8 re-reads high-severity findings. How many lenses read them, and a hard cap on those calls per run, are both settings. |

Every one of these is visible: each run records its calls, tokens and cache hits, and
the admin console shows usage over time. There is no month where the bill is a surprise.

**One thing to know:** the token budget is set once for the deployment, not per
configuration. A per-configuration budget would let a large, known-expensive delivery
have its own ceiling; it is not built, and it is the obvious next step if spend needs
finer control.

### Nothing personal reaches the model

Three independent layers, because one is a policy and three is a design.

1. **Masked at parse time.** Columns an administrator names are replaced as the
   workbook is read, so an unmasked value never exists anywhere downstream — not in
   memory, not in a prompt, not in a log.
2. **A tripwire on every prompt.** Each assembled prompt is scanned before it is sent
   and refused if it looks like it carries personal data. A prompt that has been sent
   cannot be recalled, so the check is in front of the send, not after it.
3. **Structure, never values.** Where the model is shown what a report looks like, it
   is shown labels and cell addresses — `dirt · Summary!Account status (B7)` — and
   never a row of data. The function that does it says so in its own documentation and
   is tested for it.

Alongside those: prompt logging is off and stays off, sample rows never enter a test
fixture, and the whole thing can run against a model inside your own network, in which
case no delivery data crosses a boundary at all.

### For the person using it

None of the above asks anything of an associate. They fill in a short form, drop the
files, and read findings. What the controls buy them is that the tool answers in half a
minute, answers the same way twice, and does not stop working because a budget ran out
mid-month.

## 12. Why certain choices were made

| Choice | Why |
| --- | --- |
| The model never compares or computes | Comparisons by a model are unreliable and unexplainable; by code they are exact and auditable. |
| The OSL is the source of truth | The customer's requirement is what the delivery is measured against; the configuration and reports are validated against it, never the other way round. |
| Nothing personal ever reaches the model | Sample rows are masked at parse time, a tripwire refuses any prompt that looks like it carries personal data, and an associate's note is refused at save if it does. |
| Identical content is never sent to the model twice | A cache keyed on content means re-runs and repeated sections cost nothing and answer identically. |
| One relational database, no extra infrastructure | SQLite for a laptop, Postgres for scale, chosen by one setting. Nothing else to run. |
| Login is optional and off by default | The tool works on an internal network with no accounts; when accounts are wanted, every action already carries a name. |
| Rules are data an administrator edits | The people who understand the deliveries shape the checks, without a release. |
| A learned rule starts in shadow | Its precision is unknown until it meets real data; a false-positive flood costs trust that takes months to earn back. |
| The report is frozen | What was signed off is what stays on record. |
| A match is tolerant of spelling but strict about evidence | A rule that breaks because a customer wrote "account" instead of "accounts" raises a false alarm at the highest severity; a programme named on two generic words does the same. Both were measured, not guessed at. |
| The model may soften a serious finding, never erase one | A model agreeing with the submitter is the one answer that could hide a real problem. It buys a question for a person, not a silence. |
| A model's confidence can discard an answer, never authorise one | A model's stated confidence is not a calibrated probability. A system that lets a model skip a human by being sure fails hardest where it is most sure. |
| The review list shrinks on human verdicts, never on the model's opinion | "Ten people saw this and none of them cared" is evidence. "The AI is 92% sure" is a tone of voice. |
| The tool may revoke its own trust and never grant it | The safe direction is the only one worth automating. |

## 13. Where it runs

Five containers on the internal network: the user app, the admin console on its own
URL, the API, a background worker, and the database. The model is an in-house
endpoint; the tool talks to it over a plain HTTP interface with no vendor library, so
the provider can change without a code change.

```mermaid
flowchart LR
    U[Associate's browser] --> UI[User app]
    AD[Administrator's browser] --> AUI[Admin console]
    UI --> API[API]
    AUI --> API
    API --> DB[(Database:<br/>runs, findings, rules, queue)]
    API --> FS[(Shared files:<br/>uploads, reports, PDFs)]
    W[Worker: the nine stages] --> DB
    W --> FS
    W --> LLM[In-house model endpoint]
```

## 14. How it reaches the teams

Four stages, each with an exit gate rather than a date.

```mermaid
flowchart LR
    R[1 Readiness<br/>platform, model, backups,<br/>compliance sign-off] --> U[2 Focus-group UAT<br/>real orders, benchmarked<br/>against the manual check]
    U --> S[3 Senior associates validate<br/>with Train AI mode on:<br/>the rules become theirs]
    S --> G[4 Region by region<br/>seniors deliver the training,<br/>manual check retired per group]
```

Ownership sits with a product owner in Global Delivery, a technical owner in
engineering, and one administrator per region. Support runs in three tiers, from the
senior associates on the floor to engineering, with escalation severities and
response times written down. Acceptance is a signature per programme per region,
against a precision and recall floor measured on real orders.

## 15. Where the build stands

**Built and tested: phases 0 through 6.18a and 6.18f.** 1,514 automated tests, every
linter and type checker clean, both applications building.

| Done | Still to do |
| --- | --- |
| The pipeline, the two apps, the frozen report and PDF | Fitting the parsers to the real file layouts, on the machine that holds them |
| Configurable checks, rules, programmes, meaning, versions and settings from the admin console | The in-house model benchmark on real files, on the target machine |
| Optional login and full attribution | The first UAT and its benchmark |
| Train AI mode end to end, with shadow rules; an administrator's own library of worked examples for the model | Compliance sign-off on retention and personal data |
| Coverage of every requirement, a fail-closed sign-off gate, and three independent second opinions merged by code | Region-by-region rollout |
| One place an administrator describes what to check in their own words, and one vocabulary for where a rule applies | **The evidence that lets the review list actually shrink** — real verdicts from real reviewers, gathered during rollout stage 3 |
| The artifacts checked against the submission before any model call, waived with a reason and printed on the report | The maturity levels, the trust numbers and the honesty sample that act on that evidence |
| Matching that survives being spelled differently, measured before and after, in the compliance rules, the named values and the programme check | |
| A second reading of a delivery's programme where the word lists miss, with the customer's own phrase offered back for one-click adoption | |
| The review-load machinery: which recurring findings reviewers have stopped needing to see, recorded with its evidence and **acting on nothing** | |
| Which engine produced each finding, a thirty-day run count, and a dated report of the manual hours displaced | |
| Training documents and the rollout plan, both current; delivery drift; four themes, locked by default | |
| Proven on a real commercial model end to end: a full run in 33 seconds and about five cents, reproducing the planted findings exactly | |

**What is deliberately not finished.** The parts of the design that decide what a
reviewer stops seeing are specified and not built, because they need evidence this
repository cannot manufacture: real verdicts from real people on real deliveries. That
evidence is gathered during the rollout, and the question it answers is written down in
advance so nobody has to invent a standard after seeing the numbers.

## 16. Glossary for a general audience

| Term | Meaning |
| --- | --- |
| OSL | Order Specification Letter: the customer's requirement, a Word document. The source of truth. |
| ETL configuration | The JSON file that told the extract what to do. Identified by the Solution Canvas config number. |
| DIRT | The data-integrity report: per-field statistics for the delivered data. |
| Finding | One place where the OSL, the configuration, and the reports disagree, with its evidence. |
| Frozen report | The one-page sign-off document, generated once and never changed. |
| Train AI mode | The mode in which associates record what they know so it can become rules, with an administrator approving every one. |
| Shadow rule | A rule that runs silently and is counted but shown to nobody, until its precision is known. |
| Configuration note | A standing note on an ETL configuration that reaches the model as background on every future run of it. |
| Artifact match check | The comparison, made by code before any question is put to the model, between what was typed on the form and what the uploaded configuration declares about itself. |
| Held run | A run whose artifacts disagree with the form. Its files are stored and nothing is lost; it starts as soon as somebody says, in one sentence, why they belong together. |
| Delivery programme | Which kind of work a delivery is: Account Monitoring, Account Solicitation, Archives, or Other. It decides which standing rules apply, and the tool checks that the documents read like the programme that was claimed. |
| Finding signature | "This same finding again": one customer, one programme, one rule, one thing it fired on. What the tool counts verdicts against when learning which findings a team has stopped needing to see. |
| Review load | The admin screen showing which recurring findings the tool *would* stop surfacing, and the evidence for each. It acts on nothing; it exists to be argued with. |
| Precision and recall | Of the findings the tool raised, how many were real (precision); of the real problems there were, how many it found (recall). The two numbers a QC tool is judged on, measured in UAT against the manual check. |

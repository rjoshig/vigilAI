# Greenlight AI — User training

**Audience:** associates who validate deliveries. **Covers:** the user app at
`http://<host>:3000`. **Last aligned with the code:** 2026-09-20, after Phase 6.18.

This document is kept current as a matter of process: `docs/phase-6.5.md` requires it
to be re-read against the product after every major milestone, and `CLAUDE.md` asks
for a check roughly every ten commits. If a screen does not match what is written
here, the document is wrong and should be fixed in the same change as the screen.

## What the tool does, in one paragraph

You upload the order's requirement spec (the **OSL**, a Word document), the ETL
configuration (JSON), and the output reports (Excel). The tool reads the OSL, works
out what it requires, traces each requirement into the configuration and then into
the reports, and shows you a list of **findings**: places where the three disagree.
The model reads and judges meaning; every comparison of values, counts, and ranges is
done by code, so a finding is exact and repeatable. You decide each finding, OK or Not
OK, and generate a frozen one-page report with a PDF.

## The journey of a run, end to end

Before the screen-by-screen detail, here is the whole thing in order. Nothing in the
middle needs you: the only two moments that do are the beginning and the end.

```
you fill the form and drop the files
        │
        ▼
  do these artifacts match what you typed?          ← code, no AI, instant
        │                        │
     they agree            they disagree
        │                        │
        │                 the run is HELD and shows you both values.
        │                 Say in one line why they belong together and it
        │                 continues — or cancel and correct the form.
        │                 Nothing has been spent either way.
        ▼
     QUEUED — and for about thirty seconds you can still cancel for free
        │
        ▼
     RUNNING — nine stages, unattended, about half a minute
        │      the AI reads and judges meaning; code makes every comparison
        ▼
   NEEDS REVIEW — it is ready for you
        │
        ▼
     you decide each finding: OK or Not OK, with a comment
        │
        ▼
     the gate: every high-severity finding decided, every gap acknowledged
        │
        ▼
     FINALIZED — one page, frozen, with a PDF. Never regenerated.
```

**Who does what.** You describe the delivery and you judge the findings. The tool reads
three documents you would otherwise hold in your head, and tells you where they
disagree. It never decides whether a delivery is acceptable — that has your name on it.

## Three different things are called "review"

The word does three jobs in this tool, and mixing them up is the commonest confusion.

| Where you see it | What it means |
| --- | --- |
| **Needs review** — a run's status | The pipeline has finished and the findings are waiting for you. It is not a verdict; it is "your turn". |
| **review** — a finding's severity | The tool is *not confident* about this one. Something did not extract cleanly, or a second reading disagreed with the first. It is asking you to look, not telling you something is wrong. Treat it as a question. |
| **Reviewing findings** — what you do | Deciding each finding OK or Not OK, with a comment. This is the judgement the whole tool exists to support. |

The middle row is the one worth remembering: **a `review` severity is the tool being
honest about uncertainty, not an accusation.** A finding it is sure about is high,
medium or low. A finding it is unsure about says so rather than guessing, because a
confident wrong answer costs more than an admitted doubt.

## Signing in

Login may be off or on, depending on how the deployment is configured.

- **Off:** there is no prompt. Everything you do is recorded against a placeholder
  account named John Doe, which reads as "login was not enabled".
- **On:** an administrator creates your account and gives you a first password. **You
  must change it the first time you sign in**, because a password someone else typed
  is known to two people. Five wrong attempts lock the account for fifteen minutes.
  A session lasts a working day and ends after an hour idle.

## The sidebar

At the top-left is the Greenlight AI logo, a traffic signal with the green lit,
beside the name and a small **User** chip; the admin console shows **Admin**. Clicking either takes you home. The same mark is the browser tab
icon.

The look of the app is one of four palettes. **Out of the box the theme is locked**,
so everyone reviewing a delivery is looking at the same colours and no picker is
shown. An administrator can unlock it under Appearance in the admin console; when
they do, the **theme picker** appears at the foot of the sidebar and steps through
the palettes with ‹ and ›. Stop on the one you want and the choice is remembered in
this browser. The sun/moon button switches the current palette between its light and
dark variants.

Under the Greenlight AI mark is a status line, and its dot breathes gently while the mode is on: **Train AI mode on** with a green dot, or
**Train AI mode off** with a grey dot. When it is on, some controls exist that do not
otherwise, and each carries a small **Train AI** tag. Everything you type into a tagged
control is recorded and reviewed by an administrator before it changes anything. See
"Train AI mode" below.

The **Admin console** link opens the administrator app in a new tab. If you are not an
administrator you can still open it, but nothing in it will let you change anything.

## Submitting a run

**Runs → New run.**

1. **Run details.** Customer name, order number, the **credit date**, and the
   **Configuration ID**, which is the order's ETL configuration number, the Solution
   Canvas config number. It is required and it repeats: the same configuration is
   run again months later, and the **credit date** and the run date, shown beside
   it on the run list and the run page, tell those runs apart. Every run still gets
   its own id. The credit date is the as-of date of the credit data; the tool checks
   that the reports carry it and raises a finding when they do not.
   Choose the **delivery programme**: Account Monitoring, Account Solicitation,
   Archives, or Other. Choose carefully: the tool checks that your inputs read like
   that programme and raises a finding if they do not, and it holds the delivery to
   the programme's rules. It checks this in two passes, so **writing about your work in
   your own words is not a problem**: first it looks for the programme's known words,
   forgiving plurals, hyphens and reordered phrases; only if it finds none does it read
   the documents properly to see what they describe. If that reading agrees with you,
   the tool says nothing and quietly offers your wording to your administrator so it
   matches next time without being asked. Say whether **suppressions were applied**; the default is No,
   because assuming Yes would let a missing suppression pass unremarked.
2. **Delivery notes** (optional). Anything about this delivery the OSL does not
   say. **Every field on the form says whether the model sees it.** Customer, order,
   configuration id, and additional notes stay with the run and are never sent to
   the model. The programme, its rules, the suppressions answer, configuration notes,
   and delivery notes reach the model as background. Accurate notes there improve
   the validation; an inaccurate one misleads it.
3. **Configuration notes.** Once you type a configuration id, any standing notes on
   that configuration appear under the field, with who wrote them. You can add one.
   A note is background for the model on every future run of that configuration; it
   never makes anything pass or fail on its own. Write one when you know something
   about this configuration that the OSL does not say.
4. **Input files.** The OSL (Word or PDF) and the configuration are required. Upload at least one
   report. The report slots you see are whatever an administrator has enabled; a
   type that is switched off simply does not appear.
   - **Several files for one report type.** Some campaigns deliver one field
     distribution per segment. Use **Add another file** on the slot and give each
     file a short label, such as "north" or "segment B". A finding names the file it
     came from, so "the field distribution is wrong" is never all you are told.
   - **Not sure what a workbook is?** Drop it into any slot and the tool compares
     its sheet names and headers with the samples an administrator has stored. When
     it is confident it offers to move the file to the right slot; when it is not, it
     shows the candidates and asks. It never moves a file without your say-so.
5. **Submit.** The tool hashes every file. If the same inputs were already run, it
   shows you that run and asks for a reason before running again, because a second
   identical run costs model calls and produces the same answer.

Some limits are set by an administrator and apply at once: how many runs may be
queued for one order number, and how many runs may start in a five-minute window. If
you hit one, the message says so and asks you to try again shortly.

## Watching a run

**Runs** lists every run with its status, who submitted it, and its queue position
while it waits. A run moves through nine stages; the run page shows which stage it is
on and refreshes itself. **Needs review** means it is ready for you.

## Explore a sample

**Explore a sample** shows an example of every artifact the tool accepts: a report
workbook cell by cell with the label beside each one, an OSL by section, a
configuration by JSON path. Values are masked exactly as they are on a real run.

It is there for two reasons. One is to see what the tool is reading. The other matters
more: with Train AI mode on, every cell, section and path has a **What should this
check?** button, so you can tell the tool about something it has never raised. Until
now you could only do that from a finding, which meant you could only talk about what
the tool had already noticed — and what you know is usually about what it said nothing
about.

## Reviewing findings

The run page shows the **traceability matrix** and the **findings**, worst first.

- Each finding has a **severity** (high, medium, low, or review), a title that says
  what disagrees with what, the evidence from all three artefacts side by side, and
  an OK / Not OK decision with a comment.
- There are three decisions. **False positive** means the finding is not a real
  problem. **Accepted risk** means it is real and the delivery goes ahead anyway, and
  it always needs a comment saying why. **Not OK** means the delivery has to change,
  and on a high or review finding it needs a comment too. The tool says so before it
  records anything, so nothing you typed is lost.
- Low-severity findings can be marked OK in bulk, as false positives. High-severity
  ones never can: every one must be decided by hand before the report can be generated.
- **Generate final report asks once**, showing the finding counts and reminding you
  that freezing is permanent: the report is stored once, never regenerated, and the
  findings can no longer be re-reviewed.

## What was checked

Above the findings is a panel headed **What was checked**. It exists because a short
findings list cannot tell a clean delivery from one nobody examined, and that is how a
compliance requirement slips through: nothing disagreed with it because nothing was
compared against it.

- Every requirement is in one of four states. **Checked against a report** means a
  check compared it with the delivery. **Traced, no report evidenced it** means it
  reached the configuration and no report shows it was applied. **Not traced** means
  nothing implements it, which is already a finding. **Verified by hand** means no
  check can express it, or the check for it could not be run.
- The panel also warns when a report arrived and **no check examined it**, which
  usually means that report type has no guide, meaning entry or named value yet.
- **"Declared as X; some words point to Y"** is the tool saying it is unsure which
  programme this delivery is, not that you were wrong. It appears when none of your
  programme's usual words are in the documents and a few of another programme's are —
  which happens honestly, for instance when a solicitation says it excludes existing
  accounts. Confirm the programme is right and mark it OK; if it keeps happening for a
  customer, ask your administrator to add that customer's wording to the programme.
- **Notices** appear here too: a second opinion the model could not give, a programme
  reading that did not run. They are not findings, and you should know about them.
- Every requirement nothing evidenced, and every check that could not be evaluated,
  needs **I have seen this** before the report can be frozen. That is not you saying
  the delivery is fine. It is the record that the gap was in front of you, and it goes
  into the frozen report with your name on it. Add a note if you raised it with
  someone.

If several readers looked at a finding, the evidence panel shows **how it was read**:
each reader, whether it agreed, and why. They each saw the same evidence and none saw
the others.
- If a requirement was extracted wrongly, edit it and press **Re-check**. Only the
  comparison stages re-run; nothing is re-asked of the model that has not changed.
- **Configuration notes given to the model** appear above the findings when the
  configuration had any. This is what the model was told as background; it is
  shown so you can judge a finding knowing the context behind it.
- **Since the previous run** appears when an earlier run of the same configuration
  id was finalized for this customer. It lists Not OK items from last time that are
  back (read these first), findings that are new and findings that went away, and
  what changed in the requirements and the configuration. Compared by code; the
  model is not involved. The same section is frozen into the report.

## Generating the report

**Generate report** is enabled once every high-severity finding is decided. The
report is one page: the header, the summary, the Not OK findings with your comments,
and expandable detail. It is **frozen**: generated once, stored, and never regenerated,
so what you signed off is what stays on record. **Download PDF** gives you the same
page as a file. The report names who submitted the run and who finalized it.

## Config history

**Config history** lists every captured configuration by configuration id and
version, with who ran it and when. From here you can copy a configuration into a new
run, and you can read, add, edit, or switch off the **notes** on a configuration.
Editing a note keeps the earlier wording; switching one off stops it applying from the
next run and keeps the text.

## Train AI mode

When the sidebar line is green, the tool is collecting what reviewers know so it can
get better. It is aimed at the senior associates who know a programme well enough to
say what should always be true of it, though anyone may write. Nothing you write here
runs: an administrator reads it, has the model draft a rule from it, and approves that
rule, which then runs silently against real deliveries for a while before it starts
producing findings anyone sees. You will hear back either way.

- **What should this check?** is wherever you form the opinion: on every finding card,
  in the evidence drawer, on every row of the traceability matrix, beside **I have seen
  this** on every coverage gap, and on the run as a whole. Use it when you know something
  the tool did not check, or when a finding fired and you know why it should not have.
  The form asks for one sentence first, then what you expect to see; kind, seriousness
  and scope sit under **Details** with sensible defaults. The control pre-fills what you
  were looking at, shown as chips you can remove, which is what makes your note usable.
- **A coverage gap is the best place to write.** When the panel says a requirement was
  traced but no report evidenced it, the tool is telling you it did not check something.
  If you know what should have been checked, say so there.
- **Findings from learned rules say so.** A card marked **Learned from an observation**
  exists because a colleague wrote a sentence and an administrator approved the rule it
  became; the evidence drawer names the rule. **Rules applied to this run**, above the
  findings, lists every administrator-written, guide, meaning-map and learned rule that
  produced a finding, and names the rules running silently in shadow.
- **You submit it once.** The button says **Submit observation**, and afterwards the
  form shows exactly what you sent, greyed out and no longer editable. That is
  deliberate: an administrator may already be reading it, and the model may already
  have drafted a rule from it, and neither should change underneath them.
  <br /><br />
  **If you got something wrong**, ask an administrator to **withdraw** it. It leaves
  every screen, you are free to write a fresh one, and the original is kept on the
  record rather than deleted. An administrator can also correct the wording in place
  if it is only a typo.
  <br /><br />
  If the tool answers that **a rule already covers this**, or that a running rule
  **says the opposite**, each rule it names carries a **Say this rule is wrong** button,
  which starts a correction pointed at that rule. That correction is the most useful
  thing you can tell an administrator.
- **My observations** lists what you have written and where it has got to, as a chain:
  **Waiting → Drafted → In shadow → Live**, or **Switched off**, or **Not taken forward**
  with the administrator's reason. Once a rule exists the card names it. The chain is
  read from the rule itself each time, so it is never stale. Configuration notes are not
  listed here: a note
  already reaches the model on every run of its configuration, and it lives on the
  configuration's own screen.
- **Do not paste account numbers, names, or any personal data.** The tool refuses to
  save text that looks like it, and tells you so, because the only moment it can be
  removed is before it is saved.

## Things the tool will refuse, and why

| It says | Why |
| --- | --- |
| "at least one output report must be uploaded" | The OSL and configuration alone cannot be validated against anything. |
| "runs are already queued for order …" | One order number cannot fill the queue by resubmission. |
| "… runs have started in the last 5 minutes" | The start-rate limit an administrator set. Try again shortly. |
| "this looks like it contains personal data" | An observation or note carried something like an account number. Remove it and save again. |
| "set a new password before continuing" | Your first sign-in. Change the password you were given. |

## Getting help

Your administrator can see every setting, every rule, and every observation in the
admin console. If a finding surprises you, the **Rules** screen there says what made
it fire.

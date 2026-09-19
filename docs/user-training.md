# Greenlight AI — User training

**Audience:** associates who validate deliveries. **Covers:** the user app at
`http://<host>:3000`. **Last aligned with the code:** 2026-09-19, after Phase 6.4.

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

The look of the app is one of three palettes chosen by the deployment (default,
light-blue-yellow, or classic-teal); the sun/moon button at the foot of the sidebar
switches the current palette between its light and dark variants.

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
   Canvas config number. The configuration id is for your information: every run
   gets its own id, and the same configuration id can be submitted as often as you
   like. The credit date is the as-of date of the credit data; the tool checks that
   the reports carry it and raises a finding when they do not.
   Choose the **delivery programme**: Account Monitoring, Account Solicitation,
   Archives, or Other. Choose carefully: the tool checks that your inputs read like
   that programme and raises a finding if they do not, and it holds the delivery to
   the programme's rules. Say whether **suppressions were applied**; the default is No,
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
4. **Input files.** The OSL and the configuration are required. Upload at least one
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

## Reviewing findings

The run page shows the **traceability matrix** and the **findings**, worst first.

- Each finding has a **severity** (high, medium, low, or review), a title that says
  what disagrees with what, the evidence from all three artefacts side by side, and
  an OK / Not OK decision with a comment.
- **OK** means the finding is not a problem (a false positive or an accepted risk).
  **Not OK** means the delivery has to change. A comment is expected on Not OK.
- Low-severity findings can be decided in bulk. High-severity ones never can:
  every one must be decided by hand before the report can be generated.
- If a requirement was extracted wrongly, edit it and press **Re-check**. Only the
  comparison stages re-run; nothing is re-asked of the model that has not changed.
- **Configuration notes given to the model** appear above the findings when the
  configuration had any. This is what the model was told as background; it is
  shown so you can judge a finding knowing the context behind it.

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
get better. Nothing you write here runs; an administrator reads it, has the model
draft a rule from it, and approves that rule, which then runs silently for a while
before it starts producing findings. You will hear back either way.

- **What should this check?** appears on the run page and on every finding. Use it
  when you know something the tool did not check, or when a finding fired and you
  know why it should not have. Say what you expect, how serious a breach would be,
  and how far it applies: this customer, this programme, or everywhere. The control
  pre-fills what you were looking at, which is what makes your note usable.
- **My observations** lists what you have written and what became of it: waiting,
  synthesized into a rule, or rejected with the administrator's reason. You can edit
  an observation until an administrator picks it up.
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

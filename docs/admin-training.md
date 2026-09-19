# Greenlight AI — Administrator training

**Audience:** whoever operates the tool: enables users, sets the model, tunes limits,
and turns what reviewers know into rules. **Covers:** the admin console at
`http://<host>:3001`. **Last aligned with the code:** 2026-09-19, after Phase 6.4.

Kept current under `docs/phase-6.5.md`: re-read against the product after every major
milestone, and checked roughly every ten commits per `CLAUDE.md`.

## What an administrator is responsible for

Three things, in order of how often they come up.

1. **Keeping the tool honest about what it checks**: the artifact types it accepts,
   the samples it learns layouts from, the rules it runs, and their state.
2. **Turning what reviewers know into rules**, through the training queue, with a
   person at every gate.
3. **Operating it**: accounts, the model, throughput, retention, and the settings that
   used to live in `.env`.

Everything you change is audited with your name, and most of it takes effect on the
next request or the next run, with no restart.

## Signing in, and the first sign-in

When admin login is on and no administrator exists, the tool creates one: username
`admin`, password `admin123`. **You must change it the first time you sign in**, and
a deployment that is not on a laptop refuses to serve at all until you do. Create your
own account and a second administrator before you rely on the bootstrap one.

**Users** is where accounts live, for both administrators and users. There is no
self-registration: you create the account, give a first password, and the person
changes it at first sign-in. Accounts are deactivated, never deleted, so what a
person did stays attributed to them. You cannot deactivate the last administrator.

## The sidebar

The logo and the name sit at the top-left, with a small **Admin** chip, where the user app
shows **User**, so the two are never mistaken. Clicking them goes home.

## The sidebar indicator

Under the mark: **Train AI mode on** (green) or **off** (grey). When it is on,
reviewers can record observations and they arrive in your queue. The switch itself is
on the Settings screen.

## Artifact types

What the tool accepts: the OSL, the configuration, and each report type. For each:

- **Enable or disable** it. A disabled type disappears from every user's upload form
  at once. Built-in types can be switched off but never deleted, because the fixed
  checks look them up by key; a type you defined can be deleted while no run has used
  it, and switched off afterwards.
- **Define** it: a label, what it is for the person uploading it, and **what the AI
  should look at**, in plain words. Leave the guidance empty and the model reads the
  document exactly as it always did; this is additive, never a substitute for the OSL.
- **Samples**, up to three per type, each with a label such as the customer or the
  year. You can view a sample cell by cell, download it, and remove it. Named values
  resolve against the samples, and workbook type detection compares uploads with
  them, so a type with no sample cannot be detected and its checks cannot be tested.
- **Named values** are pointers into a report that checks refer to by name. Prefer a
  label lookup over a cell address: it survives an inserted row.

## Delivery programmes

Account Monitoring, Account Solicitation, Archives, and Other. Each carries **standing
instructions**: the compliance regime that is true of every run in that programme and
that an OSL usually does not restate. They reach the model as background, labelled as
background. A programme can be switched off so users stop seeing it.

## Checks and compliance rules

**Checks** are cross-report comparisons over named values, written as an expression
that code evaluates. Describe one in plain English and the model proposes the named
values and the expression; you correct it, **test it against the samples**, and
activate it. **Compliance rules** say what must be present in every configuration in
scope. Both are versioned; a change never edits an old finding.

## The training queue

**Training** is where what reviewers wrote arrives. Two cards.

**Observations.** Each shows the author, what they pointed at (a cell, a field, an OSL
clause, a configuration path, or a finding), and what they wrote. **Configuration
notes** appear here too, marked with the configuration id; they are already acting as
background for that configuration and you may leave them at that, switch one off, or
promote it. For any observation you may:

- **Reject** it, with a reason. The reason is shown to the author. A rejection with no
  explanation reads as the tool ignoring the person, and the loop only works while
  people keep contributing.
- **Select several and Synthesize.** One model call turns the group into candidate
  rules. The model proposes a schema-shaped rule and nothing else; a statement it
  cannot express comes back as unsupported with the reason, and a statement that
  reads as an instruction to the model is refused. The observations are **marked as
  synthesized, never removed**: asking again says so rather than doing it twice.

**Candidates.** Each shows the drafted rule, its reasoning, its source observations,
and any **conflicts** with rules that already exist. Before approving:

- **Replay** it. The tool counts how many recent finalized runs the rule touches and
  how many of those findings reviewers already dismissed. A rule that would have
  fired on thirty runs that were all fine is a bad rule, and this is where that
  shows rather than next month.
- **Approve** it. The rule is created in **shadow**: it runs on every run and its
  findings are counted, but no reviewer sees them. Narrow the scope if the candidate
  proposed a wider one than the evidence supports; the default is the narrowest that
  fits, because an under-scoped assumption is the most common cause of a noisy rule.
- **Reject** it, with a reason. It keeps its sources so a later attempt can start
  from them.

## Rules

Every rule the tool holds, whatever its origin: shipped, written here, or learned.
Filtered to **active** by default; shadow, disabled, and deleted are one click away.
Search covers the name, the reasoning, and what the rule checks. This is the screen to
open when a finding surprises someone: it says what made it fire.

Each rule shows how often it fired, how often its findings were dismissed, and when it
last fired. **A high dismissal rate usually means an under-scoped rule, not a wrong
one**: narrow it before you disable it.

Actions, each requiring you to **type the word**, because a rule change reaches every
future run:

| Action | What it does |
| --- | --- |
| **activate** | Takes a shadow rule live. Do this with its fired and dismissal numbers in front of you; there is no automatic bar. |
| **disable** | Switches it off, reversibly. Where a noisy rule goes. |
| **enable** | Switches it back on. |
| **delete** | Soft. It stops running at once and can be restored for six months. |
| **restore** | Brings a deleted rule back, switched off, so you look before it runs again. |

After six months a deletion becomes permanent, but a record survives so findings on
old runs still explain themselves. **No rule ever expires on its own**; a rule unfired
for a year is either load-bearing or dead, and only a person can tell which.

## Settings

Every runtime setting, grouped: Model, Training, Login, Throughput, Uploads,
Retention, Platform. Beside each value is **where it came from**: set here, from
`.env`, or the built-in default. A value you set here wins over `.env`; **Revert** puts
it back and says what it will revert to. The **change history** at the foot says who
changed what and from what.

- **Model.** Provider, base URL, model name, and the API key, which is stored
  encrypted, never shown again, and only accepted when the server has a master key
  configured. **Test connection** makes one cheap call with the saved settings; do
  this before a run fails at stage two.
- **Training.** The Train AI switch, whether approvals go into shadow (leave it on),
  and how many recent runs a replay reads.
- **Login.** Both switches, session lifetime, idle timeout, minimum password length,
  and the lockout rules. Turning admin login off asks for a second click, because it
  leaves the console open to anyone who can reach it.
- **Throughput.** Runs in flight, runs started per window, the window, the longest
  acceptable queue wait, and queued runs per order number.
- **Uploads and Retention.** The size limit, and how long runs are kept. Shortening
  retention asks for a second click: the next sweep deletes anything past the new
  window.
- **Platform**, read-only: the database URL, the data directory, and the bind
  address. Each is needed to reach or protect the settings store itself, so none can
  live inside it.

## Reference data

**Aliases** map the names an attribute goes by across the OSL, the configuration, and
the reports; a missing alias is the usual reason a check "could not evaluate".
**Masked columns** name the report columns whose values are replaced before anything
reaches the model. Add to it whenever a new layout carries personal data.

## Usage

Runs per day, tokens, cache hit rate, and the per-rule statistics. The cache hit rate
is the number to watch: identical content is never sent to the model twice, and a rate
that drops means something is changing prompts or inputs on every run.

## A weekly routine that keeps the tool honest

1. Read the training queue. Reject what cannot be a rule, with reasons; synthesize
   what can.
2. Look at shadow rules with their numbers. Activate the ones that have earned it.
3. Sort Rules by dismissal rate. Narrow or disable the noisy ones.
4. Check the change history on Settings for anything you did not expect.
5. Confirm the artifact types still match what customers actually send; add a sample
   for any layout that surprised the detector.

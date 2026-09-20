# Greenlight AI — Administrator training

**Audience:** whoever operates the tool: enables users, sets the model, tunes limits,
and turns what reviewers know into rules. **Covers:** the admin console at
`http://<host>:3001`. **Last aligned with the code:** 2026-09-20, after Phase 6.12a.

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

## Tell the tool

The first item in the sidebar, and the one to reach for when you are not sure which of
the other screens a thing belongs on. Write **one** statement in your own words — "the
account review file must never have a blank origination date", "billing count must never
exceed the delivered count" — choose where it applies, and press **Tell the tool**.

What happens next is the training loop, not a new one. The tool decides which existing
surface the statement belongs on, drafts the rule there, and puts it in the queue as an
ordinary candidate. **Nothing runs until you approve it**, and an approved rule starts in
shadow like any other.

Three answers are possible, and two of them create nothing:

- **A candidate.** It names the surface and shows the draft, with a link into the queue
  where you approve or reject it as usual.
- **Background.** Some things are worth the tool knowing but are not something a
  delivery can pass or fail — "the second tab is the reissue file". The tool says so and
  points you at the artifact type's AI context or the standing instructions. It does not
  turn it into a rule that would then be wrong.
- **A question.** When the statement could be two things, or names nothing the tool can
  check, you get the question back and nothing is created. That is the answer working,
  not failing: a rule on the wrong surface is a finding nobody can explain.

Occasionally the tool reads a statement one way and drafts it another. It says so
instead of hiding it, and that is your cue to read the draft carefully before approving.

This screen does not replace the ones below. They are the expert view, they show exactly
what runs, and they stay the place where things are really managed.

### Which screen holds what

The front door answers this for you most of the time. When you want to go straight to
the right screen, these are the three groups that genuinely overlap, and what actually
separates them.

| These all do the same job | And differ in |
| --- | --- |
| Validation guides, meaning entries, named values | how they locate a cell in a report |
| Programme rules, compliance rules, judgment checks | who evaluates "this must hold": the model reading, code comparing, or the configuration being present |
| An artifact type's AI context, standing instructions, configuration notes | nothing, at the prompt — all three reach the model as background. Choose by how wide it is: one artifact type, one programme, one configuration |

## Artifact types

What the tool accepts, in three tabs so the kinds are never confused: **Requirements
(OSL)**, a Word or PDF document; **Solution Canvas (ETL configuration)**, the config
JSON; and **Reports**, the Excel workbooks. Named values and validation guides live
under Reports, because that is what they point into. Every type shows its definition
version as `v1.0`, `v1.1`, … (the first save is `v1.0`). For each type:

- **Enable or disable** it. A disabled type disappears from every user's upload form
  at once. Built-in types can be switched off but never deleted, because the fixed
  checks look them up by key; a type you defined can be deleted while no run has used
  it, and switched off afterwards.
- **Define** it: a label, what it is for the person uploading it, and **what the AI
  should look at**, in plain words. Leave the guidance empty and the model reads the
  document exactly as it always did; this is additive, never a substitute for the OSL.
- **Samples.** For the OSL and the configuration, grouped by who they belong to:
  **Global** (read by every programme that has none of its own) and one box per
  **delivery programme**, so a variant for Account Solicitation has its own place.
  Reports keep one box, because their layouts are the same for every programme. Up
  to three per box, each with a label such as the customer or the year and **notes**:
  how this variant differs and what to look for. The notes on the OSL and the
  configuration samples reach the model when it maps that scope. You can view a sample, download it, and remove it: a report cell by cell, an
  OSL section by section with each paragraph numbered `¶1, ¶2…`, and a
  configuration block by block with its JSON path. Named values
  resolve against the samples, and workbook type detection compares uploads with
  them, so a type with no sample cannot be detected and its checks cannot be tested.
- **Named values** are pointers into a report that checks refer to by name. Prefer a
  label lookup over a cell address: it survives an inserted row.
- **Guide.** A validation guide per report type: an ordered list of entries, each
  naming a cell or a label in the report, what it means, where it answers to in the
  OSL (a section, a phrase, or both) and in the configuration (a JSON path), and
  what to validate. Save it and the examples fill themselves from the samples. The
  model reads the guide as background on every run; it never becomes a requirement.
  An entry with a configuration path and a comparison (**equals** or **reconciles
  within a tolerance**) that resolves on a sample also becomes a **check, born in
  shadow**, on the Rules screen with origin "from a validation guide": it runs, its
  findings are counted, and no reviewer sees them until you activate it there.
  Leave the guide empty and the model reads the report exactly as it always did.
- **Versions.** Every save of a type, its samples included, keeps a snapshot. The
  **Versions** button lists the last ten with who, when, and what changed; **Revert**
  puts one back, after you type `revert`, and appears as a new version so nothing is
  ever lost. A removed sample's workbook stays on disk while a listed version still
  names it, so a revert brings the file back too.

## Meaning

Where each OSL requirement answers to, globally and per delivery programme. Pick a
scope, check the **samples in scope** (a programme's own where it has any, else the
global ones; upload them on Artifact types, choosing *Belongs to*), and press
**Map**. The model reads every OSL section against the configuration blocks and the
report cells and proposes, per requirement, the configuration path and the report
cells, with a question when it cannot place one. Rows come back **proposed** or
**open** (with the model's question). Correct a row's path, report cell or wording,
add your note, and **Confirm**: a row with a configuration path, a report cell that
resolves on a sample and a comparison becomes a **shadow check** on the Rules screen;
a suggested compliance rule becomes a shadow compliance rule. **Reject** retires
both. The bar above the rows confirms, rejects or deletes a selection under one
typed word. A programme entry with the same key as a global one replaces it on that
programme's runs. **By report cell** is the same guide editor as on Artifact types.
Everything here reaches the model as background; code does the comparing.

## Delivery programmes

Account Monitoring, Account Solicitation, Archives, and Other. Each carries **standing
instructions**: the compliance regime that is true of every run in that programme and
that an OSL usually does not restate. They reach the model as background, labelled as
background. A programme can be switched off so users stop seeing it.

Each programme also carries **keywords** and **rules**. The keywords are what the
tool greps the OSL, configuration, and report headers for to confirm a run really is
that programme; a run declared as one programme with none of its words gets a
finding. The rules are sentences true of every delivery in the programme, each with a
strictness: **must** (a breach is a high finding), **should** (medium), or
**advisory** (low). The model reads each delivery against them and names what it
breaks; the strictness decides how serious that is, and code applies it. Add as many
rules as the programme needs; switch one off from the Rules screen when it misfires.

**Rule versions.** A programme's rule set is versioned as a whole: adding, editing,
or changing the state of a rule makes a version. **Rule versions** on the card lists
the last ten; reverting restores the wording, strictness and state of every rule as
they were, and a rule that did not exist then is deleted (restorable from the Rules
screen for six months).

## Checks and compliance rules

**Checks** are cross-report comparisons over named values, written as an expression
that code evaluates. Describe one in plain English and the model proposes the named
values and the expression; you correct it, **test it against the samples**, and
activate it. **Compliance rules** say what must be present in every configuration in
scope. Both are versioned; a change never edits an old finding.

**Editing and deleting.** Every rule's wording is edited on its own screen (a
compliance rule inline, a check through the same dialog that drafted it; each edit
bumps the version). **Every delete asks you to type `delete`**, and long lists have a
checkbox per row and a bar that deletes the selection under one typed word. Checks and
compliance rules deleted this way are restorable from the Rules screen for six months.

**Scope.** Every check and compliance rule applies **everywhere**, to **one delivery
programme**, or to **one customer**. A rule scoped to Account Solicitation is never
evaluated on an Account Monitoring run, and a run with no programme sees only global
and customer rules. Pick the scope on the form; the list shows it in words, never as a
stored token.

There is a fourth scope you never pick: a rule learned from a note written against one
ETL configuration applies to **that configuration** and no other, and the form shows it
without letting you change it. A scope that names nothing — a programme with no code, a
customer with no name — covers nothing, so the form will not save one.

Scopes written before the vocabulary was unified still read and still work; nothing was
rewritten in the database, and a rule becomes canonical the next time somebody saves it
(ADR-037).

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

Every rule the tool holds, whatever its origin: shipped, written here, learned, or
compiled from a validation guide.
Filtered to **active** by default; shadow, disabled, and deleted are one click away.
Search covers the name, the reasoning, and what the rule checks. This is the screen to
open when a finding surprises someone: it says what made it fire. **Edit** jumps to
the screen that owns the rule's wording; a checkbox per row and the bar above the
table apply one state change to many rules under one typed word.

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
Retention, Appearance, Platform. Beside each value is **where it came from**: set here, from
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
- **Appearance.** The **default theme** every browser starts on, in both apps, and
  **Lock the theme**, which hides the picker everywhere and applies the default. A
  person's own choice wins for their browser until you lock; the change reaches open
  tabs within a minute, no redeploy.
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


## What the model reads, and how much of it (Phase 6.11)

**Three lenses, or one.** Stage 8 reads each high-severity finding a second time.
`LLM_VERIFY_LENSES` decides who does the reading. `single`, the default, is the one
second opinion the tool has always asked for. Naming lenses —
`delivery,compliance,requirements` — has three readers see the same evidence
independently, never each other's answers, with code merging them: all agree and the
finding is verified; any disagreement sends it to a person with each reason shown on
the evidence panel. A lens can lower confidence and can raise a question from the same
evidence, which becomes a Review item. It can never make a finding more serious.

They do not talk to each other, deliberately (ADR-034). Three readers over three rounds
would cost up to nine times the calls, would converge on whichever answer sounded most
confident, and would leave a record nobody could replay.

Leave it at `single` until the golden-set benchmark compares the three against it. What
reviewers see should change on evidence. Setting it empty turns verification off, which
each run then reports as a notice.

**A candidate rule is checked before you see it.** Synthesis drafts a rule, then reads
it back against the statements it came from: does it say what they said, and does it
overlap a rule that already exists. At most one redraft follows, and both versions are
kept on the candidate, so the distance between the model's first attempt and what you
approve is visible.

**Approving a candidate that overlaps an existing rule now asks which.** **Supersede**
disables the rule it replaces, naming this one as its successor; **keep both** says you
have looked and they cover different ground. Approve alone is refused, because
overlapping rules accumulate quietly and are very hard to untangle later.


## Asking for a second approver (ADR-036)

Each delivery programme has a **second approver** switch, off by default. With it on, a
run in that programme cannot be frozen when the reviewer marked **OK** something the
programme treats as serious — a breach of a rule you called `must`, or a compliance
rule the configuration does not implement — until somebody else signs.

Three things about it are worth knowing before you turn it on.

- **It is a signature, not a re-review.** The second person is shown what was waved
  through and says the run can be frozen. Nothing claims they redid the work.
- **It has to be someone else.** An approval from the reviewer who made those decisions
  is refused. That is the whole of what the control asserts.
- **It does nothing while login is off.** Everyone is then the same placeholder
  account, so a "second" approver is the same person and no affected run could ever be
  frozen. Rather than deadlock, the rule stands down. If you want this control, turn
  login on first (see the deployment checklist). A gate nobody can pass is worse than
  no gate.

Who approved, when, and what they covered are recorded on the frozen report.

## A weekly routine that keeps the tool honest

1. Read the training queue. Reject what cannot be a rule, with reasons; synthesize
   what can.
2. Look at shadow rules with their numbers. Activate the ones that have earned it.
3. Sort Rules by dismissal rate. Narrow or disable the noisy ones.
4. Check the change history on Settings for anything you did not expect.
5. Confirm the artifact types still match what customers actually send; add a sample
   for any layout that surprised the detector.

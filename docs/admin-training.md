# Greenlight AI — Administrator training

**Audience:** whoever operates the tool: enables users, sets the model, tunes limits,
and turns what reviewers know into rules. **Covers:** the admin console at
`http://<host>:3001`. **Last aligned with the code:** 2026-09-21, after Phases 6.19b and 6.20.

Kept current under `docs/phase-6.5.md`: re-read against the product after every major
milestone, and checked roughly every ten commits per `CLAUDE.md`.

<!-- guide 1: What an administrator is responsible for -->
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

**Users** is where accounts live. There is no self-registration: you create the account,
tick the roles it holds, give a first password, and the person changes it at first
sign-in. Accounts are deactivated, never deleted, so what a person did stays attributed to
them. You cannot deactivate or demote the last administrator — see "Who may do what: the
three roles" below.

## The sidebar

The logo and the name sit at the top-left, with a small **Admin** chip, where the user app
shows **User**, so the two are never mistaken. Clicking them goes home.

At the foot of the menu, **Guide** opens the parts of this document you will come back
to: which surface a thing belongs on, what improves the QC in the order it pays off, how
to read the numbers, who may do what, and what is never editable. It is built from this
document, so the two cannot drift, and **Show the Guide** under Appearance turns it off in
both apps for a deployment that trains another way.

Which items you see depends on what your account holds. A reviewer's menu is shorter than
an administrator's — see "Who may do what: the three roles" below — and a screen reached by
typing its URL says so rather than showing an empty page.

## The sidebar indicator

Under the mark: **Train AI mode on** (green) or **off** (grey). When it is on,
reviewers can record observations and they arrive in your queue. The switch itself is
on the Settings screen.

<!-- guide 2: The front door, and which surface a thing belongs on -->
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
| An artifact type's AI context, a worked example | whether you are telling the model something about this work, or showing it a finished answer to copy the shape of. Neither is a rule |

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

**Why this screen is worth an afternoon.** Without a mapping the model works out where
every requirement lands *from scratch, on every run* — reading the OSL, then the
configuration, then the reports, and deciding which part answers which. That is the step
it is least certain about, and the one it can answer differently on two runs of the same
delivery. One confirmed row does two things at once: **the AI reads it** at tracing and
verification, so it stops deriving the answer and spends its attention on whether the
delivery is right; and **code turns it into a check** it runs itself, with no model and
no tokens, giving the same answer every time. What you get is fewer requirements coming
back as *could not trace*, the same requirement resolving the same way every month, and a
deterministic check you did not have to write. You confirm rather than the model because
a wrong mapping is worse than none — it teaches the tool the wrong place to look.

### Correcting or removing what somebody submitted

Feedback is submitted once: the author's form locks after they send it, so nothing
changes underneath you while you are reading it. Two controls are yours.

- **Withdraw** takes it off every screen and frees the author to write a fresh one.
  What you reach for when somebody submitted the wrong thing — the wrong finding, a
  half-finished sentence. The row is kept, because nothing in the training record is
  ever deleted; it is simply no longer in anybody's way.
- **Reject**, with a reason, says it was considered and not acted on. The author sees
  the reason on **My observations**. Use it when the observation was fair and the answer
  is no; use **Withdraw** when it should not have been submitted at all.

You can also **edit the wording** in place, which is the right move for a typo. Every
edit bumps the version, so the trail survives the convenience.

## What on each screen reaches the model

Every field you can write carries a marker saying what it does to a run, in the same
six words the user app uses. They are facts about the run rather than help, so they
stay visible whatever **Explain each screen** is set to.

One of the six can be turned off, and only one: **Settings → Appearance → Show
setup-only markers** hides *Used for setup, not for runs*, which otherwise repeats under
every sample workbook on the screen. The switch cannot hide the markers that say a field
reaches the model or is checked by code — those say where your words end up, and you
keep them whatever you set (ADR-046).

| Marker | What it means for what you type |
| --- | --- |
| **Helps the AI** | Rendered into the prompt as background. Better context here means better findings; it never makes anything pass or fail. |
| **Checked by code** | Compared against the artifacts by code. It can produce a finding, and the same inputs always give the same answer. |
| **Read by a person** | Shown to whoever reviews or signs off. Nothing automated acts on it. |
| **Your own note** | Kept with the run. Reaches no model and no check. |
| **Identifies the run** | How the run is found, grouped, and compared with earlier ones. |
| **Used for setup, not for runs** | The AI reads it while you set things up. No run reads it; what you build from it is what a run uses. |

Three places where the distinction is not obvious and is worth knowing:

- **A check is one or the other, and you choose which.** An *expression* check is a
  formula code evaluates at no token cost. A *judgment* check sends its instruction and
  the named values you list to the model on **every run in its scope** — which is why
  the form says use it sparingly. The model answers pass, fail or review; **code sets
  the severity**, always.
- **A compliance rule's reasoning does more than explain.** It appears on the finding,
  and it is *what the model is told the control is* when code cannot find the path
  (Phase 6.15). Describe the control in the words a configuration might use for it —
  "screens against the OFAC SDN list" — rather than only citing the policy that
  requires it. A rule described well is found under a name you never anticipated; one
  described only as a regulation reference is not.
- **A sample workbook helps the AI, but never on a run.** This is the marker people
  most often read as *nothing*, and that is the wrong reading. The AI and the tool use
  your samples for four things while you set up: working out which uploaded file is
  which, what a named value points at, the example values a validation guide shows, and
  the suggestions on the **Meaning** screen — the one place the model reads a sample's
  layout directly. None of it happens when a delivery is checked: the file is not
  opened, and a better sample improves runs only through the definitions you build from
  it. One thing does travel, so it is worth knowing: where a guide entry lands on a
  sample, that cell's value is quoted to the model as an example on every run the guide
  applies to. **That is why samples must be made-up files, never real customer data**
  (ADR-003).

The full register, derived from the code rather than from memory, is
[`model-context.md`](model-context.md).

## Delivery programmes

Account Monitoring, Account Solicitation, Archives, and Other. Each carries **standing
instructions**: the compliance regime that is true of every run in that programme and
that an OSL usually does not restate. They reach the model as background, labelled as
background. A programme can be switched off so users stop seeing it.

Each programme also carries **keywords** and **rules**. The keywords are what the
tool greps the OSL, configuration, and report headers for to confirm a run really is
that programme; a run declared as one programme with none of its words gets a
finding.

**The AI is a second pass, not the first.** When none of a programme's words appear in
a delivery, the tool reads the documents once and says which programme they sound like.
It is never asked whether the submitter was right — code compares its reading with what
was declared and decides what to do. If it agrees with the submitter, the finding is
either dropped or reduced to a question, and **the words it quoted appear on the
programme's card as suggestions**. Clicking one adds it to the word list, and from then
on the match is made in code and the AI is not asked again for that wording. Nothing is
added until you click.

**Two things about keywords are worth knowing before you edit them.** Matching is
forgiving of spelling but not of vocabulary: `existing accounts` finds *existing
account*, `invitation to apply` finds *invitation-to-apply*, and `portfolio review`
finds *ongoing review of the portfolio* — so you never need to add plurals, hyphenated
forms, or the same two words in the other order. What it cannot do is guess a word you
have not given it, so **add the words your customers actually use** (an abbreviation
like *ITA*, a vendor's name for a campaign) as you meet them.

**Every keyword must mean its programme and no other.** A word two programmes both list
is ignored when the tool decides which programme a delivery *looks like*, because it
cannot tell them apart. A word the delivery business uses generally — *snapshot*,
*historical*, *monthly* — belongs in no list at all: it appears in every programme's
paperwork, and putting it in one makes the tool confidently name the wrong programme.
Two such words shipped in the Archives list until Phase 6.17a measured what they cost. The rules are sentences true of every delivery in the programme, each with a
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

**Judgment checks run.** A check can be a **formula**, which code evaluates for free on
every run, or a **judgment**: an instruction in plain words plus the named values the
model may see. The model reads only those values — never a report, never a row — and
answers pass, fail or review; code records the verdict at the severity you set, and an
answer the model is not confident about goes to a person as a review item. A judgment
check costs one model call on every run in its scope, so the form says *use sparingly*
and asks which named values to show before it lets you activate it. Until 6.13c a
judgment check was accepted and never ran.

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

## Worked examples

**What this screen is for.** Every prompt in the tool ships with worked examples: a
section of a requirements document and the requirements it states, a pair of things and
whether one implements the other. They are what makes a mid-size model reliable on a
narrow task. This screen is where you add yours, drawn from the deliveries you actually
see, when the model reads something the way your documents do not.

**An example is a pair, never an instruction.** You give what the model would be shown
and a good answer, in the JSON that stage returns. There is no box here that tells the
model what to do. The block reaches the prompt after the built-in examples, under a line
saying the examples show the shape of a good answer and are not rules (ADR-038).

**What it is not.** An example is not a rule. It changes how the model *reads*; it
cannot make anything pass or fail. Every comparison is still made by code against a
check, a compliance rule or a field constraint. If what you want is a rule, use Tell the
tool.

**The six stages.** Reading the OSL, describing the configuration, tracing a requirement
to the configuration, judging named values, placing a statement, and drafting a rule from
observations. Open a stage to see the examples that ship in the prompt, read-only, above
your own.

**What the console refuses.**

- An answer that is not valid for that stage is refused with the field named. An example
  the pipeline could not parse would teach the model a shape it then rejects.
- A fifth active example on one stage is refused. A prompt carries four, so a fifth
  would look live and reach nothing; take one out of use first.
- An example that looks like it carries personal data is refused on save, not later.

**Scope.** An example is scoped like every other definition: everywhere, one delivery
programme, one customer, or one configuration. The narrowest scopes are shown to the
model first.

**Teaching from a correction.** Under the stages, the screen lists the two places
somebody has already corrected the model: requirements reviewers rewrote, and rules you
approved from what reviewers wrote. **Use as example** turns one into a worked example.
A confirmed mapping on the Meaning screen has the same button. Nothing is promoted on
its own — a correction says one reading was wrong, not that it generalises, and that
judgement is yours.

**Versions.** Each stage keeps its last ten versions with revert, like any other
definition.

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

- **Replay** it. Each of the last few finalized runs has its stored reports parsed
  again and this rule run over them, by the same evaluator the pipeline uses. You are
  told which runs it would have fired on and what it would have said. A rule that
  would have fired on thirty runs that were all fine is a bad rule, and this is where
  that shows rather than next month. Reading the files takes a moment, so the replay
  is queued and the card fills in when it finishes.

  Two things it does not claim. Firing means the rule would have raised a finding, not
  that the finding would have been right. And the count of related findings reviewers
  already dismissed is an estimate: the rule has produced no findings yet, so the
  nearest honest signal is what they judged about the same attribute.
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
  and how many recent finalized runs a replay evaluates the rule against.
- **Login.** Both switches, session lifetime, idle timeout, minimum password length,
  and the lockout rules. Turning admin login off asks for a second click, because it
  leaves the console open to anyone who can reach it.
- **Throughput.** Runs in flight, runs started per window, the window, the longest
  acceptable queue wait, and queued runs per order number.
- **Uploads and Retention.** The size limit, and how long runs are kept. Shortening
  retention asks for a second click: the next sweep deletes anything past the new
  window.
- **Appearance.** The **default theme** every browser starts on, in both apps, and
  **Lock the theme**, which hides the picker everywhere and applies the default. Also
  **Explain each screen**, **Show setup-only markers**, and **Show the Guide** — the last
  of which offers or withdraws the Guide in both sidebars and nothing else; no check, no
  rule and no run is affected by it.
  **Locking is on by default**, so both apps start out looking the same for everyone;
  switch it off and each person's own choice wins for their browser. The change
  reaches open tabs within a minute, no redeploy.
- **Platform**, read-only: the database URL, the data directory, and the bind
  address. Each is needed to reach or protect the settings store itself, so none can
  live inside it.

## Reference data

**Aliases** map the names an attribute goes by across the OSL, the configuration, and
the reports; a missing alias is the usual reason a check "could not evaluate".
**Masked columns** name the report columns whose values are replaced before anything
reaches the model. Add to it whenever a new layout carries personal data. This card is
**administrators only**, and a reviewer sees the screen without it: the aliases and field
labels are theirs, and naming a masked column is the one control here whose failure is
invisible.

## Usage

Three tabs, because three different questions get asked of this screen.

**Tool health** is runs per day, tokens, cache hit rate and the per-rule statistics. The
cache hit rate is the number to watch: identical content is never sent to the model
twice, and a rate that drops means something is changing prompts or inputs on every run.

**By person** is who is using the tool and how it is going for them, over 7, 30, 90 or
180 days. Three columns matter most and are deliberately kept apart, because they have
different causes and different fixes:

| Column | What it usually means |
| --- | --- |
| **Failed** | The pipeline raised. Usually the tool's problem — a layout, a parser. |
| **Held** | What was uploaded disagreed with what was typed on the form. Usually something a person can be shown how to avoid: the wrong month's configuration, a customer name that does not match the file. |
| **Re-runs** | The same order came back for another go. Something was wrong either way. |

A rate is flagged only when it is well above **this deployment's own average**, shown in
the line under the tab, and never for somebody with fewer than five runs — over three
runs a rate says nothing. Click any count to open those runs in the user app. **CSV**
downloads every person in the period, not the page on screen, with more columns than the
table shows and the averages on the last line.

This is a count of what happened to somebody's runs, not a judgment on them, and nothing
on it reaches a model. Use it to find where the tool is letting a group of people down
(ADR-048).

**What it displaced** is the hours report, over a date range you choose.


## Review load — what reviewers stop needing to see (Phase 6.18a)

**Read this screen before you believe anything on it.** Nothing on it is being acted
on: every reviewer still sees every finding, exactly as before. It shows what the tool
*would* hide, so you can judge whether it should.

The tool has recorded every verdict a reviewer gave since the review screen existed,
and until now nothing read them. This screen adds them up.

A **signature** is the identity of *this same finding again*: one customer, one
delivery programme, one rule, and one thing it fired on. A blank score column and a
blank state column are two signatures however much they share a rule — learning that
one is harmless must never silence the other. Trust is learned per customer per
programme, so what your teams learn about a customer's solicitation work never applies
to that customer's archive work.

A signature is listed as **would be hidden** once it has been shown to a reviewer **ten
times and waved through every single time**. A count rather than a rate, and no
exceptions in it: *"shown to a person ten times and never once mattered"* is a sentence
that survives an audit, and *"nine times out of ten"* is not, because the tenth is the
one that would have been hidden.

Two things put a signature on the **blocked** list, where it stays:

- **A reviewer judged the finding real** — marked it Not OK, or accepted it as a known
  risk, which means they agreed it was true and chose to carry it. One of those
  outranks any number of dismissals, forever, until somebody clears it deliberately.
- **It fires at high severity.** These are never hidden at any level of evidence. The
  goal is a reviewer who reads only the serious findings, not one who reads none.

Every row carries the sentence explaining its state and the runs its evidence came
from, so a decision can be checked against the deliveries it was learned from rather
than taken on trust.

**What to do with it.** Leave it for some weeks, then open it and ask the question the
banner asks: *it would have hidden these — was any of them real?* If the answer is no,
that is the evidence for letting reviewers stop seeing them. If any of them was real,
the bar was wrong and the tool has told you so before anybody was hurt by it.


## What the model reads, and how much of it (Phase 6.11)

**Three lenses, or one.** Stage 8 reads each high-severity finding a second time.
**Second-opinion lenses** on the Settings screen (or `LLM_VERIFY_LENSES` in `.env`) decides who does the reading, and **Lens calls per run** caps what it may cost. `single`, the default, is the one
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

**Approving a candidate that overlaps an existing rule asks which.** The overlap names
the rule it found, and the card offers two buttons in place of one: **Approve — replace
the older rule** disables the rule it replaces, naming this one as its successor;
**Approve — keep both** says you have looked and they cover different ground. Overlaps
are found again at the moment you approve, so a rule created since the draft was made
is not missed. Overlapping rules accumulate quietly and are very hard to untangle later.

**A shadow rule's findings are yours to see.** Reviewers never see them, which kept the
review queue clean and left nobody able to say a shadow finding was wrong, so every shadow
rule showed a dismissal rate of zero. The Rules screen now carries **Shadow findings** on
any rule in shadow or that has fired: what it found, on which run, and a **Not a real
problem** button that records a dismissal. That dismissal rate is what decides whether to
activate the rule (ADR-040).

**Every rule kind now runs in shadow and carries statistics.** A learned compliance rule
names the configuration path it looks for, runs in shadow like a check, and its findings
count on the Rules screen; a programme rule put in shadow stays hidden from reviewers.
**Last fired** is the date of the run the rule fired on, not the date somebody reviewed
it. A compliance rule with an expected value is checked for that value, not just for the
path being present.


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

<!-- guide 5: Who may do what: the three roles -->
## Who may do what: the three roles

An account holds any of three roles, and it can hold several. **What somebody may do is
the union of what their roles grant**, so adding one never takes another away.

| Role | What it is for |
| --- | --- |
| **user** | Submits runs and decides findings in the user app. No admin console at all — the link is not even offered. |
| **reviewer** | Everything in this console that is about *judging the work*: approving what the tool learned, the rule surfaces, worked examples, the figures, and the reference data a delivery's vocabulary needs. |
| **admin** | All of that, plus what *defines the deployment*: delivery programmes, artifact types, meaning, accounts, settings, and masked columns. |

The line is between **judging the work** and **defining the deployment**. A reviewer
decides whether a rule is right. An administrator decides what a programme is, who has an
account, and what the tool is allowed to send to a model. Different jobs, different blast
radius, and the second group should be much smaller.

Two things to know when you assign them:

- **A senior associate is a user and a reviewer**, not an administrator. That is the
  person the whole training loop was built for: they know a programme well enough to
  approve what the tool learned from it, and they should not be creating accounts or
  changing what the tool may send to a model.
- **Masked columns sit on the admin side** even though the rest of Reference data does
  not. Naming a column there is what keeps personal data out of every prompt; it is the
  strongest control in the product and the one whose failure is least visible, because
  nothing goes wrong on screen when a column stops being masked.

The checkboxes on the Users screen are checkboxes and not a dropdown for a reason: the
roles are not exclusive. **You cannot remove the last administrator**, by unticking the
box or by deactivating the account, including your own — locking everybody out of the
console cannot be undone without editing the database.

None of this applies until login is switched on. With it off there is one placeholder
account that everything is attributed to, it holds every role, and nothing is gated.

<!-- guide 3: What improves the QC, in the order it pays off -->
## What improves the QC, in the order it pays off

Five things are worth your time, and they are not equally worth it. In order:

1. **Worked examples.** One example of a judgement the tool got wrong, at the stage it
   got it wrong, changes its answers on every run afterwards. Nothing else you can do has
   that reach for that little effort.
2. **Artifact guidance and AI context.** Telling the tool how to read a workbook — which
   tab is what, which heading row to trust — fixes a whole class of "could not evaluate"
   at once, because a check that cannot find its column is not a check.
3. **Programme keywords in the customer's own vocabulary.** The keyword check is what
   confirms a delivery is the programme it claims to be. It matches text, so it only
   works in words the customer actually uses: add *their* phrase, not the industry's.
4. **Standing instructions on a programme.** Background the tool should carry into every
   run of that programme. Useful, bounded, and read as background rather than as a rule —
   which is also why it is fourth: it informs answers rather than deciding them.
5. **Masked columns**, whenever a new layout arrives carrying personal data. This one is
   not about quality at all; it is the control that has to be right regardless.

What is *not* on that list: writing more rules. A noisy rule costs a reviewer attention
on every run, forever. Sort Rules by dismissal rate before you add another one.

<!-- guide 4: How to read the numbers -->
## How to read the numbers

- **Fired and dismissed**, per rule. Fired is how often it produced a finding; dismissed
  is how often a person said that finding was not a real problem. The ratio is the
  number that matters, and a high one means the rule is spending reviewer attention
  rather than saving it.
- **Shadow** means a rule is being evaluated and its findings are recorded but shown to
  nobody. It is how a rule earns activation: you can see what it *would* have raised,
  against real deliveries, before anybody has to read it.
- **Precision**, here, means: of the findings this rule raised, how many a person agreed
  with. It is measured from verdicts people actually gave, so it is only as meaningful as
  the number of verdicts behind it — a rule with four results has no precision worth
  quoting.
- **Review load** shows what reviewers would stop needing to see. It is **acting on
  nothing**: it reports, and no finding is hidden because of it. That is deliberate, and
  it stays that way until the numbers behind it have been read by a person who can judge
  them.
- **Usage** counts runs per person and per period. It is there to show where the work
  actually is, not to rank anybody.

<!-- guide 6: What is never editable, and why -->
## What is never editable, and why

Four settings are shown read-only on the Settings screen, and no console anywhere can
change them: the **database URL**, the **data directory**, the **bind address**, and the
**master key**. Each one is needed to reach or protect the settings store itself. A
database URL that lived in the database could be pointed somewhere else and then never
read back; a master key stored under its own encryption cannot decrypt itself. They are
environment configuration, changed where the service is deployed and nowhere else.

<!-- guide 7: A weekly routine that keeps the tool honest -->
## A weekly routine that keeps the tool honest

1. Read the training queue. Reject what cannot be a rule, with reasons; synthesize
   what can.
2. Look at shadow rules with their numbers. Activate the ones that have earned it.
3. Sort Rules by dismissal rate. Narrow or disable the noisy ones.
4. Check the change history on Settings for anything you did not expect.
5. Confirm the artifact types still match what customers actually send; add a sample
   for any layout that surprised the detector.

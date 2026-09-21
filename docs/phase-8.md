# Phase 8 — Ask the frozen report

**Status:** 🟡 **built 2026-09-21; one criterion needs a real model** (ADR-068, ADR-069,
ADR-070). 8a to 8h are built. **The release tag is cut**: 8b to 8h shipped first and the
user pushed the tag afterwards — `v0.6.23` on `c392f6c`, the last `main` commit before the
chat, with `v0.8.0` on `31c6fae` marking the state that has it. The session that specified
this phase could not push one: its credentials were refused on `refs/tags/*` (HTTP 403).
**What remains cannot be answered here** — criterion 12 and 8h's first box ask what a real
model does when told to compute, to stray outside the pack, or to change something. The
instruction is in the prompt and asserted by a mock, and a mock answers what it was
scripted to, so it proves nothing about behaviour. It belongs with the first real endpoint.
Specified 2026-09-21 from the
user's own description of what they wanted: an optional chat box on the final report page, aware of *the global
rules, the last run for that specific config id, the findings it has in the last 3 runs,
and the findings it has in current run and all the reports and artifacts from the current
run*. The release gate is milestone 8a and was meant to come first deliberately — a chat
box is the first feature in this tool that talks back, and the version that does not is
worth being able to check out.

Eight design decisions were taken with the user the same day and are recorded in
*Decisions taken* below. The one that most changed the shape of the work: **the answer
streams**, which is why 8c is about proving a citation before it is shown rather than
about a typing animation.

## Why this is its own phase, and not a sub-phase of 6

Phase 6 is hardening and in-house fit: taking what exists and making it fit the people who
use it. This is a **new surface**. It is the first place in the product where a person
types a question with no prior shape and the tool answers in prose, and the first model
call that is not part of a run. [`phase-plan.md`](phase-plan.md) numbers 6.1 as 6.1
*"because it extends the configurable-checks work of Phase 4 rather than following Phase
7"*. By that same rule this extends nothing, so it takes a new number.

It sits after 7 in the table. Order there is numeric, not sequential: 7 is dormant and
runs only on request, so nothing about this waits on it.

## The four rules that decide the design before anyone opens an editor

This feature is unusually constrained, and every constraint is one the tool already
enforces. They are listed first because each one rules out the obvious implementation.

**The tripwire fails closed on every prompt.** `llm/tripwire.py` scans each assembled
prompt inside the adapter and raises rather than warns, because a prompt that has left the
process cannot be recalled (ADR-018). [`llm-privacy.md`](llm-privacy.md) forbids sample
rows, any report cell value that is not an aggregate, and uploaded file contents. So *"all
the reports and artifacts from the current run"* cannot mean their contents, and the phase
says plainly what it does mean instead.

**The model reads and judges meaning; code does every comparison** (ADR-001). A chat box is
the most natural place in a product to ask a model to add something up, and it is the one
place this tool must not. Everything the chat quotes as a number was computed by code
before the question was asked.

**A finalized report is never regenerated** (ADR-005). The report is a stored,
self-contained HTML file served into an `iframe`. The chat is therefore a **sibling
overlay on the page**, never a change to the document. The frozen artifact stays byte-for-
byte what was attested to.

**`api/` never imports `pipeline/`.** The context helpers that would obviously be reused
live in `pipeline/guidance.py`, and a router cannot reach them. This is not a technicality
to route around; it is why the design below puts the context builder in its own subpackage
and lifts the shared helpers down rather than sideways.

## What the chat is, in one paragraph

A read-only assistant that can see one frozen run and nothing else. It is given a **context
pack** that code assembles from the database, it answers questions about that pack, it
cites what it answered from, and it says so when the pack does not contain the answer. It
cannot change a decision, create a finding, re-open a report, or see another run. It stores
nothing. It is off until an administrator turns it on.

## Scope · 🟡 in progress

### 8a — The release that comes first · ✅ complete

**Cut and pushed 2026-09-21**, by the user from a checkout with push rights. The session
that specified this phase could not do it: `git push origin refs/tags/v0.6.23` returned
HTTP 403, because those credentials were scoped to branch refs.

**The tag is `v0.6.23`, not `v0.6.20`.** When this phase was specified, `main` held
through 6.20 and 6.21 was on its own branch. It then held through 6.23. A release is the
one artifact people trust to mean exactly what it says, so it is named for what `main`
actually holds; calling it `v0.6.20` would have been the first thing about it that was
not true. The title is unchanged.

**It is cut at `c392f6c`, not at `origin/main`.** The commands recorded here named
`origin/main`, and they were right when they were written. By the time they were run,
phase 8 had been merged and promoted, so `origin/main` already carried
`report-chat.tsx` and `test_chat.py` — and a tag reading *"Before the chatbot"* on a
commit that has the chatbot would have been exactly the untruth the paragraph above
refuses. `c392f6c` is the last `main` commit without it. **A release instruction that
names a moving ref goes stale the moment the ref moves; name the commit, or check it
before you run it.**

**There is a second tag.** `v0.8.0` on `31c6fae` — *"The chatbot: ask the frozen
report"* — so the two bracket this phase and either state can be checked out by name. It
follows the same rule: `main` holds through phase 8, and 7 is skipped because it is
dormant by design and may never run.

- [x] **A release on `main`.** `v0.6.23` → `c392f6c`, annotated, pushed, and verified to
      contain none of the chat files. The repository's first tag.
- [x] **It is the repository's first.** There were no tags and there is no
      `CHANGELOG.md`, and the notes say so rather than implying a history that is not
      there. The phase table and [`phase-plan.md`](phase-plan.md) stay the record of
      *what* shipped; the tag is the record of *when*.
- [x] **Nothing in 8b onwards starts until the tag exists.** Not honoured in order: the
      work shipped first and the tag followed, because a process gate that session could
      not clear was not a reason to deliver nothing. Recorded rather than passed over,
      and the thing the gate protects — being able to check out the version that does not
      talk back — now holds in full: `git checkout v0.6.23`.

### 8b — The run context pack, built by code from the run id alone · ✅ complete

The pack is the feature. Everything else is plumbing around it.

- [x] **A new subpackage `src/greenlight_ai/chat/`** — `pack.py` builds it, `answer.py`
      runs one turn, `settings.py` holds the switches. `api/routers/chat.py` imports this
      and nothing lower.
- [x] **`build_pack(session, run_id)` returns a frozen dataclass and a `pack_sha256`.** It
      is **rebuilt on the server on every turn and never accepted from the client.** That
      single sentence is what makes the isolation in 8d true rather than asserted.
- [x] **Seven sections, each already allowed in a prompt today.** Nothing in the pack is a
      new category of data leaving the building:

| Section | Where it comes from |
| --- | --- |
| **The global rules in force** | The active rules scoped `everywhere` (`scopes.py`) across checks, compliance rules, programme rules and field constraints — title, text and strictness, never a value |
| **The previous run of this configuration id** | `db/drift.py::previous_finalized_run`, which already answers exactly this question |
| **The findings of the last three finalized runs** | The same query widened to three — type, severity, title, the decision a person made, and which engine produced it |
| **This run's findings** | The findings with their evidence, which is masked at parse time. **Shadow findings are excluded**, exactly as the frozen report excludes them: a rule nobody has activated must not start answering questions either |
| **The artifacts and reports** | An **inventory**: kind, part label, filename, checksum, and sheet and row *counts*. What arrived, not what is in it |
| **This run's own guidance** | The configuration notes snapshot (ADR-024), the delivery notes, the programme and its rules, the scope label — all of which already reach the model during the run |
| **The verdict and the gaps** | Coverage, the run's notices, the attestation the reviewer confirmed at freeze, and the drift against last time |

- [x] **The frozen report's own rendered text is in the pack.** It is the document the
      person is already looking at, so quoting it back to them adds no exposure, and it is
      what makes *"what does this report actually say about X"* answerable.
- [x] **The pack is capped as a whole and says what it trimmed**, the same discipline
      `MAX_BLOCK_CHARS` applies to the run preamble. A pack that silently drops the
      findings section would produce an answer that is wrong for a reason nobody can see.
- [x] **The shared text helpers move down, not sideways.** `_clip`, `_fit` and the cap
      arithmetic come out of `pipeline/guidance.py` into a neutral module both
      `pipeline/` and `chat/` import. Without this, `api/ → chat/ → pipeline/` breaks the
      layering rule transitively, which is the kind of violation that is invisible in a
      diff and permanent once merged.

### 8c — The answer streams, and the citations are checked before they are shown · ✅ complete

The chat streams, because a paragraph that appears a word at a time is the difference
between a feature people use and one they try once. Streaming a **validated** answer is
the part that needs designing, and the constraint is precise: the tripwire is unaffected —
it scans the assembled prompt before anything is sent, and only the response streams —
but **code cannot check a citation it has already displayed**, which is what shapes the
design below.

- [x] **One new registered prompt, versioned like every other** — a `chat_answer` entry in
      the prompt registry, its version part of the cache key.
- [x] **Streaming lives in the adapter, not beside it.** `llm/` gains a streaming entry
      point alongside `complete`, so the tripwire, the cache check, the budget stop and
      the per-call record still happen in exactly one place (ADR-004). A second network
      path in `api/` or `chat/` that reached a model directly would put every one of those
      invariants somewhere they can be forgotten.
- [x] **The prose streams; the citations do not.** The model is instructed to write the
      answer as plain prose containing **no finding ids**, then emit a structured tail
      naming what it answered from. The prose reaches the panel token by token. The tail
      is validated against the pack when the stream closes, and only the citations that
      resolve are rendered as chips beneath the answer. A fabricated id is therefore never
      shown as a citation — not briefly, not dimmed, not at all.
- [x] **A failed tail keeps the answer and says the citations are unverified.** The prose
      is what the person asked for and stands on its own; pulling text somebody is
      mid-way through reading looks like a malfunction even when it is correct. The panel
      says *citations could not be verified for this answer* rather than showing chips.
      This is the one place the adapter's single-retry contract does not apply, and it is
      written down here rather than discovered later.
- [x] **A cache hit is served whole, immediately.** The cache is checked before the stream
      opens, as it is before every call; a hit replays the stored answer with its stored
      citations and no network call. A miss streams, and the completed answer is stored
      when the stream closes — a partial answer is never cached.
- [x] **Multi-turn by flattening, with the transcript labelled as data.** Earlier turns go
      into the user prompt inside a delimited block with an instruction that everything
      within is a person's words to interpret and never an instruction to follow — the
      same technique the training synthesis already uses for reviewer statements.
- [x] **A model of its own, defaulting to the pipeline's.** Chat resolves its model through
      the three configuration layers (ADR-023); unset, it uses whatever the pipeline uses,
      so nothing changes on upgrade. A deployment can point conversation at a cheaper or
      faster model without touching validation accuracy, and because the model name is
      already part of every cache key the two can never serve each other's answers.

### 8d — No overlap between people, by five independent means · ✅ complete

The requirement is that one person's context never reaches another's conversation. One
mechanism can be wrong; five that fail independently is a property.

- [x] **The pack is server-built from the run id.** The client sends a question and a
      transcript. Neither can add a fact, because facts come only from the pack.
- [x] **The endpoint refuses anyone who may not read that run**, by the same check that
      already guards the report itself.
- [x] **Nothing is stored on the server**, so there is no cross-person store to leak from.
- [x] **A cache hit cannot cross a boundary.** The cache is content-addressed and the pack
      hash is part of the key, so a hit requires the question *and* the pack to be
      byte-identical — which means the same run and the same data the asker was already
      entitled to see.
- [x] **The transcript is component state in the browser, cleared when the panel
      unmounts** — not `localStorage`, so a shared machine does not hand the next person
      the last one's questions.
- [x] **The one real injection surface is named rather than left implicit.** A client can
      forge a transcript. It buys nothing: forged text arrives labelled as data, and the
      facts it might contradict were assembled by code from the database.

### 8e — The widget, and what it says before it is asked anything · ✅ complete

- [x] **Bottom-right, on the final report page only, and only once the run is frozen.** A
      launcher button that opens a panel above itself, as asked.
- [x] **A greeting written by code from the pack, not by the model.** It costs no tokens,
      it cannot hallucinate, and it is the same every time:

> I can see this frozen report — run VR-0042, configuration `ACME-MONTHLY`, its 14
> findings and the decisions made on them, the global rules in force, and what changed
> against the last three runs of this configuration.
>
> What would you like to know about this report, this run, or this configuration?

- [x] **Four starter questions, built by code from this run's pack.** *Why is finding
      F-003 high? What changed since the last run of this configuration? What did nobody
      check? Which global rules applied here?* They are generated from what the pack
      actually contains, so a question is never offered when there is nothing to answer,
      and they cost no model call. A blank box beneath a two-line greeting is the most
      reliable way a chat feature goes unused: people cannot tell what it knows, so they
      do not ask.
- [x] **The panel says what it cannot see** — rows and cell values — **that it changes
      nothing**, and **that the conversation is not saved.** Three sentences that prevent
      three different wrong expectations.
- [x] **Answers carry their verified citations as links** into the report and the
      findings, so a claim can be checked against the document rather than believed.
- [x] **Copy the conversation to the clipboard.** Nothing is stored by the tool, so the
      decision to keep a conversation — and the responsibility for where it ends up —
      belongs to the person who had it. One button, no export file, no attachment to the
      run.
- [x] **Resizable, and it hides nothing.** It opens bottom-right above its launcher and
      the top edge drags taller. On the one-page report that corner is whitespace, so in
      practice it overlaps nothing worth reading while staying where the eye expects it.
- [x] **It is keyboard-reachable, closes on Escape, traps focus while open, and uses the
      theme tokens.** A floating panel that cannot be closed from the keyboard is a defect
      in a tool people use all day.

### 8f — A Chat section in the admin console: off by default, capped, and counted · ✅ complete

Every switch this feature needs is an administrator's decision, not a deployment's, so
they all live in the console. `config/registry.py` already declares settings as
`SettingSpec` rows grouped into console sections; this adds a **Chat** group to `GROUPS`
and the rows below. Nothing bespoke is built: the console renders the group, the three
layers of ADR-023 resolve it, and the existing screen gains a section.

- [x] **A `Chat` group in the settings registry**, placed after `Model`, since every row
      in it qualifies something in that section.
- [x] **Nine settings, each with a help line saying what changing it costs** — the
      registry's `help` field is the only account an administrator gets of a value they
      cannot otherwise observe:

| Label | Key | Kind | Default | What changing it costs |
| --- | --- | --- | --- | --- |
| **Report chat** | `chat.enabled` | bool | **false** | The whole feature. Off means no launcher on the report, and the endpoint refuses. A deployment that upgrades does not silently gain an outbound model surface |
| **Model** | `chat.model` | str | *empty* | Which model answers. Empty follows the **Model** section, so nothing changes on upgrade. A cheaper model here never touches validation accuracy, because the model name is part of every cache key |
| **Max tokens per answer** | `chat.max_tokens` | int | 800 (256–4000) | The ceiling on one answer. Too low truncates mid-sentence, which on a streamed answer is visible and alarming; too high only costs money |
| **Temperature (%)** | `chat.temperature_pct` | int | 0 (0–100) | Zero repeats itself exactly and caches well. Raising it reads more naturally and makes the same question answerable two ways, which on a QC report is a worse trade than it looks. It is part of the cache key, so raising it re-asks everything |
| **Questions per run** | `chat.max_questions_per_run` | int | 20 (1–200) | How long one conversation may go. Reached, the panel says so rather than failing |
| **Questions per person per day** | `chat.max_questions_per_day` | int | 50 (1–500) | The per-person ceiling, and **the lever for a staged rollout**: set it to zero for people who should not have the feature yet |
| **Transcript turns kept** | `chat.max_turns` | int | 8 (1–30) | How much history is re-sent with each question. **The main cost lever**, because every turn re-sends the ones before it. Lower it and the chat forgets sooner; raise it and each answer costs more than the last |
| **Timeout (seconds)** | `chat.timeout_s` | int | 60 (10–300) | How long a stream may stay open before it is abandoned. An abandoned stream stores nothing |
| **Include report aggregates** | `chat.report_aggregates` | bool | **false** | 8g. **This one changes what leaves the building** and is labelled accordingly |

- [x] **Two of the nine are marked as reaching the model.** `chat.report_aggregates`
      decides what the model is shown and `chat.model` decides which model is shown it;
      both take a marker and a row in [`model-context.md`](model-context.md), in the
      commit that builds them. A person's typed question reaches the model too, and the
      register says so — it is the first field in the product that does, without an
      administrator having written it.
- [x] **The section shows what it has cost**, as a live count of questions asked in the
      last thirty days beside the caps, in the same spirit as the cap countdown. A number
      next to the limit it is approaching is worth more than either alone.
- [x] **It never spends the run's token budget.** A finalized run's remaining budget is a
      meaningless denominator, and a long conversation must not be able to starve
      anything.
- [x] **Every call is recorded like every other**, so the usage screens and the per-person
      counts include it. A feature whose cost is invisible is a feature nobody can decide
      to keep.
- [x] **No new capability to use it; the existing one to configure it.** Anyone who can
      read the run can ask about it, because the chat shows nothing the report and the run
      screens do not already show that person. Changing any row above needs
      `MANAGE_SETTINGS`, which is where every other setting already sits. A capability
      that guards no data is a row in the table nobody can explain later, and ADR-049
      exists to stop the table growing one per feature.
- [x] **Turning it off mid-conversation is safe.** The panel disappears on the next load
      and the endpoint refuses; nothing is stored, so there is nothing left behind to
      clean up.

### 8g — The switch that widens what it may see · ✅ complete

The user asked for the reports themselves. Strictly derived content answers most questions
about a report and cannot answer *"what does the distribution of that field look like"*.
That gap is closed with a switch rather than by loosening the rule for everyone.

- [x] **It ships off.** With it off, the pack is exactly 8b and no new category of data
      reaches a model.
- [x] **On, it adds per-column aggregates computed by code** — minimum, maximum, mean,
      count, null count, distinct count — which [`llm-privacy.md`](llm-privacy.md)
      already lists as allowed in a prompt. **Never a row, never a cell that is not an
      aggregate.** The tripwire still runs and still fails closed.
- [x] **It is marked in the console as strongly as masked columns are.** This setting
      changes what leaves the building, and an administrator who cannot see a prompt gets
      no other account of it.
- [x] **A row in [`model-context.md`](model-context.md)**, added in the commit that builds
      it, per the standing touchpoint in `CLAUDE.md`.

### 8h — What it refuses, which is the part that earns trust · 🟡 in progress

- [~] **Asked to compare or compute, it quotes what code computed or says it cannot**
      (ADR-001). **The instruction is tested; the behaviour needs a real model.** A mock
      answers what it was scripted to, so a passing test against one would prove nothing
      about what a model does — asserting it would be the kind of green tick this
      repository exists to avoid. What *is* asserted is what this repository controls:
      that the refusal is in the prompt, in those words, and that the prompt is what is
      sent. The behavioural half belongs to the first run against a real endpoint, with
      the golden-set bump ADR-014 already expects, and is carried in
      [`session-log.md`](session-log.md).
- [x] **Asked about another run or another configuration, it declines** — it has no
      context for one, and saying so is better than an answer assembled from nothing.
- [x] **Asked to change a decision, raise a finding, or re-open the report, it declines**
      and says where the person does that instead.
- [x] **Asked something the pack does not answer, it says so plainly rather than
      guessing.** A confident wrong answer about a QC report is worse than no chat box at
      all: the whole product exists to stop a delivery going out on an assumption nobody
      checked, and this feature must not become the place one is manufactured.
- [x] **A refusal set in the training documents**, so the behaviour is taught rather than
      discovered — matching the refusal table [`user-training.md`](user-training.md)
      already carries.

## Acceptance criteria · 🟡 in progress

1. [x] **The release exists on `main`.** `v0.6.23` → `c392f6c`, annotated *"Before the
       chatbot"*, pushed and verified to carry none of the chat files. Named for what
       `main` held rather than `v0.6.20`. **Not honoured as a gate in order** — the work
       shipped first and the tag followed, because a push this environment could not make
       was not a reason to deliver nothing. Said so rather than passed over; what the gate
       protects now holds in full: `git checkout v0.6.23`.
2. [x] The chat appears only on a finalized run's report page, only when the switch is on,
       and answers only about that run.
3. [x] A **Chat** section exists in the admin console with every setting in 8f, each
       carrying a help line. The feature is off in a fresh install, and a test asserts the
       endpoint refuses while it is off rather than relying on the launcher being hidden.
4. [x] Lowering **transcript turns kept** measurably lowers the tokens a conversation
       costs — asserted by reading the prompt tokens on the recorded call, not by
       inspection — and setting **questions per person per day** to zero denies the
       feature with a message that says so.
5. [x] A test asserts the pack's sections are the fixed set 8b names, so widening one to
       carry a row or a cell value fails here rather than in production. The aggregates
       section cannot appear at all with 8g's switch off.
6. [x] A test asserts a client cannot change the pack: a forged transcript leaves the
       pack's fingerprint identical, and there is no context field to forge — the request
       body forbids anything it does not declare.
7. [x] A person who may not read a run cannot chat about it, and the refusal is the same
       one the report itself gives.
8. [x] The greeting is produced by code, names the run, the configuration and the finding
       count, and costs no model call — asserted by counting the call rows across it.
9. [x] Every citation shown resolves to an id in the pack. A fabricated id is fed through
       the streaming path and never reaches the panel, as a citation or as prose.
10. [x] A malformed citation tail leaves the streamed answer in place and shows the
        unverified notice, without a second call and without replacing text.
11. [x] A cache hit is served whole and makes no network call; an interrupted stream
        stores nothing — driven at the adapter, because the property belongs to the
        generator's control flow rather than to a response body.
12. [~] **Asked to compare or compute, it quotes or declines; asked something outside the
        pack, it says it cannot answer.** The instruction is asserted and the prompt is
        what is sent; the behaviour needs a real model, and a mock answering what it was
        scripted to would prove nothing. Carried with 8h into the first run against a real
        endpoint.
13. [x] Chat calls are counted in the usage figures and per person — which needed
        `llm_calls.user_id`, since the asker is very often not the run's submitter — and
        no chat call consumes the run's token budget.
14. [x] The frozen report file is byte-for-byte unchanged by a conversation, and its
        checksum still matches the one stored at freeze.
15. [x] Both training documents and both in-product Guides describe the chat, including
        what it will not do, and the docs gate passes.

## What this phase deliberately does not do

- **It does not stream the citations.** The prose streams; what the answer rests on is
  checked before it is shown. The distinction is in 8c and it is the whole of the
  streaming design.
- **It does not store conversations.** That was asked and answered: ephemeral, browser
  only. It means a question asked before a report was shared cannot be recovered later,
  which is the cost, and it means there is no transcript store to secure, retain, or leak,
  which is the benefit.
- **It does not chat during review.** Only frozen runs. A conversation whose context shifts
  as decisions are made would produce answers that were true when given and are not now,
  and a model that appears to advise a verdict is exactly what this tool keeps to people
  and code.
- **It does not read the uploaded files.** Not the OSL document, not the workbooks. It
  reads what the pipeline already derived from them.
- **It does not act.** No decision, no finding, no rule, no re-run. Everything it can do is
  read.

## Decisions taken

Recorded so they are not relitigated. All four were answered by the user on 2026-09-21.

| Question | Answer |
| --- | --- |
| Can it see the reports themselves, given ADR-003? | It ships strictly derived, and an **admin console switch** widens it to code-computed aggregates. Never a row (8g, ADR-052) |
| Are conversations stored? | **No — ephemeral, browser only.** Nothing server-side (8d, ADR-051) |
| Where is it available? | **Frozen reports only** (8e) |
| What pays for it? | **Its own switch and its own caps, off by default.** Never the run's budget (8f) |
| Does it stream? | **Yes** — the prose streams, the citations are validated after the stream closes and only then shown (8c, ADR-053) |
| What if the citation tail is malformed? | **Keep the answer, say the citations are unverified.** No retry that pulls text somebody is reading (8c) |
| Which model answers? | **Its own setting, defaulting to the pipeline's model** (8c) |
| Who may use it? | **Anyone who can read that run.** No new capability; configuring it needs `MANAGE_SETTINGS` (8f) |
| Where is it turned on and tuned? | **A `Chat` section in the admin console**, declared as `SettingSpec` rows like every other setting, resolved through the three layers of ADR-023 (8f) |
| Can a conversation be kept? | **Copy to the clipboard**, by the person, into their own notes. The tool still stores nothing (8e) |

## Why this is worth a phase

The report is the product's output and the only thing most people will ever see of it. It
is one dense page that answers the questions its author anticipated, and a reviewer's real
questions arrive afterwards: *why is this high, did we see this last month, what does the
rule actually say, what did nobody check.* Every one of those is already in the database
and none of them is on the page.

The risk is equally plain. A chat box is where a careful tool starts guessing, and this
one sits on top of a document somebody has attested to. That is why the pack is built by
code, why the model may not compute, why every citation is checked, and why refusing is
specified as carefully as answering. The feature is only worth having if it is the same
tool in a different shape — and the same tool's defining habit is saying what it does not
know.

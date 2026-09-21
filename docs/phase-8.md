# Phase 8 — Ask the frozen report

**Status:** ⬜ **not started** — specified 2026-09-21 from the user's own description of
what they wanted: an optional chat box on the final report page, aware of *the global
rules, the last run for that specific config id, the findings it has in the last 3 runs,
and the findings it has in current run and all the reports and artifacts from the current
run*. Nothing here is built. It is **queued behind 6.21**, and behind one thing that is
not a phase at all: **a GitHub release must exist before a line of this is written**, so
that the product as it stands can be returned to. The release gate is milestone 8a and
comes first deliberately — a chat box is the first feature in this tool that talks back,
and the version that does not is worth being able to check out.

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

## Scope · ⬜ not started

### 8a — The release that comes first · ⬜ not started

- [ ] **A GitHub release on `main`, before any code in this phase is written.** Tagged
      `v0.6.21` once 6.21 has merged, titled **"Before the chatbot"**, with notes covering
      phases 0 through 6.21.
- [ ] **It is the repository's first release.** There are no tags and no `CHANGELOG.md`
      today, and the release notes say so rather than implying a history that is not
      there. The phase table and [`phase-plan.md`](phase-plan.md) have been the release
      record until now, and they stay the record of *what* shipped; the tag is the record
      of *when*.
- [ ] **Nothing in 8b onwards starts until the tag exists.** This is the whole reason 8a
      is a milestone rather than a note.

### 8b — The run context pack, built by code from the run id alone · ⬜ not started

The pack is the feature. Everything else is plumbing around it.

- [ ] **A new subpackage `src/greenlight_ai/chat/`** — `pack.py` builds it, `answer.py`
      runs one turn, `settings.py` holds the switches. `api/routers/chat.py` imports this
      and nothing lower.
- [ ] **`build_pack(session, run_id)` returns a frozen dataclass and a `pack_sha256`.** It
      is **rebuilt on the server on every turn and never accepted from the client.** That
      single sentence is what makes the isolation in 8d true rather than asserted.
- [ ] **Seven sections, each already allowed in a prompt today.** Nothing in the pack is a
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

- [ ] **The frozen report's own rendered text is in the pack.** It is the document the
      person is already looking at, so quoting it back to them adds no exposure, and it is
      what makes *"what does this report actually say about X"* answerable.
- [ ] **The pack is capped as a whole and says what it trimmed**, the same discipline
      `MAX_BLOCK_CHARS` applies to the run preamble. A pack that silently drops the
      findings section would produce an answer that is wrong for a reason nobody can see.
- [ ] **The shared text helpers move down, not sideways.** `_clip`, `_fit` and the cap
      arithmetic come out of `pipeline/guidance.py` into a neutral module both
      `pipeline/` and `chat/` import. Without this, `api/ → chat/ → pipeline/` breaks the
      layering rule transitively, which is the kind of violation that is invisible in a
      diff and permanent once merged.

### 8c — One turn, through the adapter that already exists · ⬜ not started

- [ ] **One new registered prompt, versioned like every other** — a `chat_answer` entry in
      the prompt registry, its version part of the cache key.
- [ ] **No new network path, and no streaming in this phase.** `complete(system, user,
      schema)` stays the only way to reach a model (ADR-004), so the tripwire, the cache,
      the budget check and the per-call record all apply without being re-implemented.
      Streaming would mean a second code path around every one of those, which is a large
      price for a typing animation. The widget shows a working indicator instead, and the
      decision is recorded so it can be revisited rather than rediscovered.
- [ ] **Multi-turn by flattening, with the transcript labelled as data.** Earlier turns go
      into the user prompt inside a delimited block with an instruction that everything
      within is a person's words to interpret and never an instruction to follow — the
      same technique the training synthesis already uses for reviewer statements.
- [ ] **The answer is schema-constrained** — an answer, its citations, whether the pack
      contained enough to answer, and a refusal reason. Nothing downstream parses prose.
      Loose parsing of free-form model output is where code starts trusting something
      nobody checked.
- [ ] **Code checks every citation resolves** to an id that is actually in the pack, and
      drops the ones that do not. A fabricated finding id is the failure mode that would
      most damage trust in this feature, and it is cheap to make impossible.

### 8d — No overlap between people, by five independent means · ⬜ not started

The requirement is that one person's context never reaches another's conversation. One
mechanism can be wrong; five that fail independently is a property.

- [ ] **The pack is server-built from the run id.** The client sends a question and a
      transcript. Neither can add a fact, because facts come only from the pack.
- [ ] **The endpoint refuses anyone who may not read that run**, by the same check that
      already guards the report itself.
- [ ] **Nothing is stored on the server**, so there is no cross-person store to leak from.
- [ ] **A cache hit cannot cross a boundary.** The cache is content-addressed and the pack
      hash is part of the key, so a hit requires the question *and* the pack to be
      byte-identical — which means the same run and the same data the asker was already
      entitled to see.
- [ ] **The transcript is component state in the browser, cleared when the panel
      unmounts** — not `localStorage`, so a shared machine does not hand the next person
      the last one's questions.
- [ ] **The one real injection surface is named rather than left implicit.** A client can
      forge a transcript. It buys nothing: forged text arrives labelled as data, and the
      facts it might contradict were assembled by code from the database.

### 8e — The widget, and what it says before it is asked anything · ⬜ not started

- [ ] **Bottom-right, on the final report page only, and only once the run is frozen.** A
      launcher button that opens a panel above itself, as asked.
- [ ] **A greeting written by code from the pack, not by the model.** It costs no tokens,
      it cannot hallucinate, and it is the same every time:

> I can see this frozen report — run VR-0042, configuration `ACME-MONTHLY`, its 14
> findings and the decisions made on them, the global rules in force, and what changed
> against the last three runs of this configuration.
>
> What would you like to know about this report, this run, or this configuration?

- [ ] **The panel says what it cannot see** — rows and cell values — **that it changes
      nothing**, and **that the conversation is not saved.** Three sentences that prevent
      three different wrong expectations.
- [ ] **Answers carry their citations as links** into the report and the findings, so a
      claim can be checked against the document rather than believed.
- [ ] **It is keyboard-reachable, closes on Escape, traps focus while open, and uses the
      theme tokens.** A floating panel that cannot be closed from the keyboard is a defect
      in a tool people use all day.

### 8f — Off by default, capped, and counted · ⬜ not started

- [ ] **A feature switch, default off**, like login. A deployment that upgrades does not
      silently gain an outbound model surface.
- [ ] **Its own caps** — questions per run, questions per person per day, tokens per
      answer, turns of transcript — resolved through the three configuration layers
      (ADR-023) so an administrator can change them without a deploy.
- [ ] **It never spends the run's token budget.** A finalized run's remaining budget is a
      meaningless denominator, and a long conversation must not be able to starve
      anything.
- [ ] **Every call is recorded like every other**, so the usage screens and the per-person
      counts include it. A feature whose cost is invisible is a feature nobody can decide
      to keep.

### 8g — The switch that widens what it may see · ⬜ not started

The user asked for the reports themselves. Strictly derived content answers most questions
about a report and cannot answer *"what does the distribution of that field look like"*.
That gap is closed with a switch rather than by loosening the rule for everyone.

- [ ] **It ships off.** With it off, the pack is exactly 8b and no new category of data
      reaches a model.
- [ ] **On, it adds per-column aggregates computed by code** — minimum, maximum, mean,
      count, null count, distinct count — which [`llm-privacy.md`](llm-privacy.md)
      already lists as allowed in a prompt. **Never a row, never a cell that is not an
      aggregate.** The tripwire still runs and still fails closed.
- [ ] **It is marked in the console as strongly as masked columns are.** This setting
      changes what leaves the building, and an administrator who cannot see a prompt gets
      no other account of it.
- [ ] **A row in [`model-context.md`](model-context.md)**, added in the commit that builds
      it, per the standing touchpoint in `CLAUDE.md`.

### 8h — What it refuses, which is the part that earns trust · ⬜ not started

- [ ] **Asked to compare or compute, it quotes what code computed or says it cannot**
      (ADR-001). This is tested, not hoped for.
- [ ] **Asked about another run or another configuration, it declines** — it has no
      context for one, and saying so is better than an answer assembled from nothing.
- [ ] **Asked to change a decision, raise a finding, or re-open the report, it declines**
      and says where the person does that instead.
- [ ] **Asked something the pack does not answer, it says so plainly rather than
      guessing.** A confident wrong answer about a QC report is worse than no chat box at
      all: the whole product exists to stop a delivery going out on an assumption nobody
      checked, and this feature must not become the place one is manufactured.
- [ ] **A refusal set in the training documents**, so the behaviour is taught rather than
      discovered — matching the refusal table [`user-training.md`](user-training.md)
      already carries.

## Acceptance criteria · ⬜ not started

1. [ ] The `v0.6.21` release exists on `main` before any other criterion is started.
2. [ ] The chat appears only on a finalized run's report page, only when the switch is on,
       and answers only about that run.
3. [ ] A test asserts the pack contains no report cell value that is not an aggregate, and
       fails when a section is widened to include one.
4. [ ] A test asserts a client cannot change the pack: a forged transcript and a forged
       context field alter nothing about what the model is shown.
5. [ ] A person who may not read a run cannot chat about it, and the refusal is the same
       one the report itself gives.
6. [ ] The greeting is produced by code, names the run, the configuration and the finding
       count, and costs no model call.
7. [ ] Every citation in an answer resolves to an id in the pack; fabricated ones are
       dropped before the answer is shown.
8. [ ] Asked to add two numbers from the report, the chat quotes the computed figure or
       declines. Asked something outside the pack, it says it cannot answer rather than
       answering.
9. [ ] Chat calls are counted in the usage figures and per person, and no chat call
       consumes the run's token budget.
10. [ ] The frozen report file is byte-for-byte unchanged by the presence of the chat —
        its checksum after a conversation matches the one stored at freeze.
11. [ ] Both training documents and both in-product Guides describe the chat, including
        what it will not do, and the docs gate passes.

## What this phase deliberately does not do

- **It does not stream.** The reason is in 8c: one adapter entry point is worth more than
  a typing animation. Revisit it as its own decision if people ask for it.
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

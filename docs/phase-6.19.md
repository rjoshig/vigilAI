# Phase 6.19 — Say what helps, and teach it in the product

**Status:** ⬜ **not started** — specified 2026-09-20 from an audit the user asked for.
Two things that belong together because they answer the same question from two
distances: *what does what I type actually do, and how do I use this well?*

**Nothing here is a defect in the engine.** Everything the tool computes, it computes
correctly. This is about whether the people using it can tell.

## Part A — The "Helps the AI" marker, where it is missing

### What the marker is, and why it is not decoration

`CLAUDE.md` puts it plainly: *an administrator cannot see a prompt, so the label is the
only account they get of where their words end up*. `<FieldEffect>` never hides, unlike
the help tooltips, and states one of five things — **Helps the AI**, **Checked by code**,
**Read by a person**, **Your own note**, **Identifies the run**.
[`model-context.md`](model-context.md) is the register it quotes.

A field that reaches the model and does not say so is the same defect as shipping it
undocumented — and worse in one specific way: somebody writing a careful paragraph into
an unmarked box has no reason to think it matters, so they write less than they would
have, and the tool is worse for it.

### The audit, 2026-09-20

Twelve surfaces carry a marker today and are correct. **Thirteen fields reach the model,
or decide what the model is shown, and say nothing.** Two of them are the ones most
likely to change what the tool finds.

#### Admin console — reaches the model, unmarked

| Screen | Field | What it actually does |
| --- | --- | --- |
| **Examples** | A worked example's *given* and *answer* | Shown to the model at six stages (ADR-038). **This is the screen that most directly teaches the model**, and it is the one with no marker at all. |
| **Meaning** | A confirmed mapping | Reaches stages 4 and 8 through the guide block, and compiles into a shadow check. |
| **Artifact types → Guide** | A validation guide entry | Reaches stages 4 and 8 as background. |
| **Artifact types** | A sample's **notes** | Read by the model during the mapping interview for that scope. |
| **Tell the tool** | The administrator's sentence | Sent to the model, which says which surface it belongs on (ADR-037). |
| **Training queue** | An observation's statement and expectation | Sent to the model, which drafts a candidate rule from them (ADR-021). |
| **Delivery programmes** | A **programme rule**'s title and text | Read by the model at stage 8, which names what a delivery breaks; **code** grades it by strictness. The screen explains this in prose above the list — it is not hidden — but the field itself carries no marker, so it reads as less consequential than the standing-instructions box directly above it, which does. |
| **Delivery programmes** | **Keywords** | Compared by code, *and* they decide whether the model is asked to read the delivery at all (ADR-045). The programme's **name** is sent in that prompt. The hint text is good and current; there is no marker. |

#### Admin console — protective, and unmarked

| Screen | Field | What it actually does |
| --- | --- | --- |
| **Reference data** | **Masked columns** | Decides what **never** reaches the model, by replacing values at parse time. Arguably the most important marker in the product, and there is none: the field that protects personal data should say so loudest. |
| **Reference data** | **Aliases** | Used by code to match a field named differently in three documents. No model involvement, which is itself worth saying. |

#### User app — unmarked

| Screen | Field | What it actually does |
| --- | --- | --- |
| **New run** | **Delivery programme** | Reaches the model as background on every stage, selects which programme rules it reads, and triggers the check that the documents read like that programme. **Consequential, unmarked, and sitting between two fields that are marked.** |
| **New run** | **Suppressions applied** and **deliverable count** | Both reach the model as background; the count is also checked by code against the files that arrived. |
| **New run** | **Order number** | Identifies the run. `record`, not `model` — but saying so is the point. |
| **Review → observation** | The reviewer's statement and expectation | Sent to the model, which drafts a rule from them. A reviewer typing into this box is teaching the tool and is not told so. |

### A claim that is false until this is done

[`user-training.md`](user-training.md) says **"Every field on the form says whether the
model sees it."** It does not: the delivery programme, the order number, the suppressions
answer and the deliverable count are all unmarked. The sentence has been corrected to say
what is true today, and **it goes back to the stronger wording in the same commit that
makes it true again**.

### Scope · ⬜ not started

- [ ] A marker on every field in the two tables above, each stating what that field does
      rather than repeating a generic sentence.
- [ ] **Start with the two that change results most**: the delivery programme on the new
      run form, and worked examples in the admin console.
- [ ] The masked-columns marker says plainly that it is what keeps personal data out of
      every prompt.
- [ ] A test that fails when a screen writing to a model-reaching field has no marker,
      so this audit does not have to be repeated by hand. `tests/test_model_context_register.py`
      already keeps the register honest against the code; this is the same idea pointed
      at the UI.
- [ ] `user-training.md` restored to the stronger sentence, in the commit that earns it.
- [ ] `model-context.md` re-read end to end: every row in it should be findable on a
      screen, and every marked field should be a row in it.

## Part B — A Guide in the product, one for each audience

### The problem

`docs/user-training.md` and `docs/admin-training.md` are good, current, and **in a
repository nobody using the tool will ever open**. A new associate is given a URL and a
login. Everything they know about the tool they learn from the screen, from a colleague,
or from a training session weeks earlier that they half remember.

The rollout plan asks the seniors from stage 3 to deliver an hour of training per region.
An hour teaches how to click. It cannot teach the things that actually decide whether the
tool is worth having: *which fields are worth writing carefully, what the tool is not
looking at, when to disagree with it.*

### What to build · ⬜ not started

**A `Guide` entry in the sidebar of each app**, reading from the training document that
already exists for that audience, so there is one source and it cannot drift. Not a copy
of the repository file rendered in a frame: a screen written for the person in front of
it, from the same content, with the sections a non-technical reader needs first.

- [ ] **User app → Guide.** Written for an associate on their first week.
- [ ] **Admin console → Guide.** Written for an administrator, which is a different job
      and a different set of worries.
- [ ] One source per audience. If a session updates the training document, the Guide
      updates; a guide that can drift from the training document is two documents.
- [ ] Reachable from the sidebar, findable without being told it exists, and readable on
      the screen somebody already has open — not a download.

### What each Guide must actually answer · ⬜ not started

The audit's finding applies here too: people do not need more words, they need the
**few things that change the outcome** said plainly and early.

**The user Guide:** · ⬜ not started

- [ ] **What the tool is doing on your behalf**, in four sentences and without jargon.
      It reads the requirement, reads the configuration, reads the reports, and reports
      where they disagree. It does not fix anything and does not approve anything.
- [ ] **What matters most from you**, ranked, and honestly:
      1. The **delivery programme** — it changes which rules apply and what the tool
         expects to see.
      2. The **delivery notes** — the single field where a sentence of context most
         improves what the tool finds.
      3. The **right files**, which the tool now checks before it starts.
      Everything else on the form is identification.
- [ ] **How to read a finding**, with one worked example of each severity and what the
      evidence panel is showing.
- [ ] **How to decide, and that deciding is yours.** What OK and Not OK mean downstream,
      why high-severity findings cannot be bulk-decided, and why the report is frozen.
- [ ] **When the tool is unsure, and what it says when it is.** "Could not evaluate",
      a programme it could not place, a coverage gap. A reader who understands that the
      tool distinguishes *wrong* from *unsure* will trust it correctly rather than
      uniformly.
- [ ] **Why your disagreement is worth recording**, and what happens to it: the sentence
      goes to an administrator, becomes a candidate rule, runs silently until its
      precision is known, and then counts. With the outcome visible to the person who
      wrote it.
- [ ] **What it will not catch**, said out loud. A tool whose limits are stated is
      trusted more, not less, and a reviewer who believes it catches everything is the
      failure mode this whole product exists to prevent.

**The admin Guide:** · ⬜ not started

- [ ] **The five surfaces and which one to use**, since choosing well between them is the
      main skill of the job — and *Tell the tool* exists precisely because the choice is
      hard.
- [ ] **What improves the QC, in the order it pays off.** Worked examples, artifact
      guidance, programme keywords in the customer's own vocabulary, standing
      instructions, masked columns. With the reason each one works.
- [ ] **What to do weekly**, which the training document already has at its foot and
      which nobody will find where it is.
- [ ] **How to read the numbers**: fired and dismissed counts, what shadow is for, what
      precision means here, and the Review load screen — including that it is acting on
      nothing and why that is deliberate.
- [ ] **What is never editable and why** — the database URL, the data directory, the
      bind address, the master key.
- [ ] **How to keep the tool honest**: the golden set after a prompt change, the
      benchmark after a rule change, the sample that keeps a mature configuration
      measured.

### The tone it has to be written in · ⬜ not started

- [ ] **Factual.** No claim that is not true today. Where something is coming, say it is
      coming. Where a number is a target rather than a measurement, say which.
- [ ] **For a non-technical reader.** No JSON, no stage numbers, no ADR references. "The
      configuration file" rather than "the ETL config", and never "the LLM".
- [ ] **Short where it can be.** The parts that change behaviour come first; the
      reference material comes after and is skimmable.
- [ ] **Honest about limits**, everywhere. This is the tone the rest of the product is
      already written in and the Guide should not be the place it slips.

## Acceptance criteria · ⬜ not started

1. [ ] Every field in Part A's tables carries a marker that says what that field does.
2. [ ] A test fails when a model-reaching field has no marker.
3. [ ] `user-training.md`'s "every field says whether the model sees it" is true again.
4. [ ] Both apps have a **Guide** in the sidebar, from one source per audience.
5. [ ] A person who has never seen the tool can read the user Guide and submit and review
       a run without asking anybody. **Tested on a person, not asserted.**
6. [ ] Both Guides state what the tool does not do, and neither overstates a number.
7. [ ] The rollout plan's training item points at the Guide rather than at a repository
       file nobody will open.

## Why this is worth a phase

The tool's accuracy is not in question here; its **legibility** is. Both halves are the
same problem at different distances: a field that does not say what it does, and a
product that does not say how to use it well. Either one alone makes the tool worse than
it is — the first quietly, by making people write less than they would have, and the
second loudly, on the day a region is rolled out and nobody can remember the hour of
training they were given.

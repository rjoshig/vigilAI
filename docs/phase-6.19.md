# Phase 6.19 — Say what helps, and teach it in the product

**Status:** 🟡 **Parts A and C complete** (2026-09-20), Part B not started. Specified
from an audit the user asked for, and extended with what a session of use turned up.
The parts belong together because they answer the same question from different
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

### One correction to the audit

Two of the thirteen were overstated, and the record should say so rather than quietly
shrink. **There is no deliverable-count field on the new-run form** — the count is not
exposed there, so there was nothing to mark. And several of the fields listed as
"unmarked" did carry the information as ordinary prose beneath the box; what they lacked
was the *standing marker*, which is visually consistent, cannot be switched off, and is
the thing a reader learns to look for. The gap was real, and it was inconsistency rather
than silence in those cases. The genuinely silent ones were worked examples, meaning
entries, validation guides, sample notes, the *Tell the tool* sentence, the observation
dialog, programme rules, keywords, and masked columns.

### Scope · ✅ complete

- [x] A marker on every field in the tables above, each stating what that field does
      rather than repeating a generic sentence.
- [x] **The two that change results most.** The **delivery programme** on the new-run
      form now says it is one of the most important fields there and why. **Worked
      examples** say they are the most direct way an administrator teaches the model.
- [x] The **masked-columns** marker says plainly that it is what keeps personal data out
      of every prompt, and that naming a column there is the strongest control an
      administrator has.
- [x] Fields that reach *nothing* are marked too, because a reader deciding how much care
      to take deserves to know which it is: the order number identifies the run, and an
      example's "why it is here" note is never shown to the model.
- [x] **A test that fails when a marker is removed** —
      `tests/test_field_markers.py`, seventeen checks. It also asserts the two apps word
      the marker identically, and that `<FieldEffect>` never consults the tooltips
      setting: what a field does to a run is not a tip for beginners, and a console that
      stops saying it once somebody ticks a box lies to its experienced users. Verified
      by breaking a marker and watching it fail.
- [x] `user-training.md` restored to the stronger sentence, in the commit that earned it.

### What a session of use added · ✅ complete

The marker set grew a sixth kind, and one screen's worth of that came from somebody
reading the console and asking a question the console should have answered.

- [x] **A `reference` marker — *"Used for setup, not for runs"*.** The register and the
      component docstring both used the idea of reference material; there was no marker
      for it, so a sample workbook and an artifact type's description carried nothing at
      all. Silence is the wrong answer there: the AI *does* read the samples, just never
      during a validation run. It reads them for workbook-type detection, named values, a
      guide's worked examples, and the mapping interview — the one place it sees a
      sample's layout directly.
- [x] **The register's claim about samples was wrong, and is corrected.** It said *a
      sample's contents never enter a validation run*. Where a guide entry's locator
      lands on a sample, that cell's value is stored on the entry and quoted to the model
      as `e.g. label=value` at stages 4 and 8. It is one named value an administrator
      chose rather than a row, and it is exactly why samples must be synthetic (ADR-003).
- [x] **That one marker is switchable, and the other five are not** (ADR-046). It says a
      field is *not* read in a run, so hiding it cannot mislead anybody about where their
      words go; on a screen of sample files it is the same sentence repeated. The switch
      is `ui.setup_markers`, in **Settings → Appearance**, on by default, and its help
      says plainly which markers it cannot touch.
      `test_only_the_setup_marker_may_be_switched_off` asserts the *shape* of the guard,
      so widening it fails even though every rendering test would still pass.
- [x] **Help tips close on the next click, wherever it lands** — the control that opened
      one, the tip's own body, or the far side of the page. Previously only a second
      click on the same 16-pixel target closed it. Done with a transparent sheet rather
      than a document listener, because a listener races the button's own handler and the
      tip either survives the click or reopens on it.
- [x] **The Meaning screen says what a mapping is for.** It had *what* a mapping is and
      not *why anybody would spend an afternoon on one*: that without it the model
      re-derives where every requirement lands on every run, which is the step it is
      least certain about; that a confirmed row both reaches the prompt and compiles into
      a code check at no token cost; and that a wrong mapping is worse than none, which
      is why a person confirms.
- [x] **[`user-training.md`](user-training.md) redrawn and brought current.** The
      end-to-end journey was ASCII art; it is now a Mermaid flowchart in the same style
      as [`presentation-brief.md`](presentation-brief.md), carrying the held branch and
      the cancel window that the prose never covered. Two diagrams were added: **where
      what you type actually goes** — the three groups of form fields and what reads
      each — and the observation's life from *Waiting* to *Live*, in the same words the
      **My observations** screen uses. All three were rendered to check they parse and
      read, rather than assumed.
- [x] **Five things the user document never mentioned**, each a screen an associate can
      meet on any given day: a **held** run and the two ways out of one, the **thirty
      seconds** in which a submission can be cancelled for nothing, the **notice bar**,
      the **maintenance page** and paused submissions, and the **?** help — which now
      closes on any click. The refusal table gained the three messages that go with them.
- [x] **"Missing before Map can run: osl, config" is now a sentence somebody can act
      on.** It named artifact keys — a correct answer to a question nobody asked. It now
      says Map reads one example of each artifact, names which is missing in words, links
      to the screen that fixes it, and says a made-up file is enough.

## Part C — What the runs and the usage screen would not tell anybody · ✅ complete

Three things a session of use asked for, each of them a question the product could not
answer about itself.

- [x] **A failed run says where it failed, not only that it did** (ADR-047). The list
      keeps its one line; the run gains the stage, the attempt and the traceback behind a
      closed disclosure with a copy button, because what happens next is that somebody
      pastes it into a ticket. Bounded at both ends and never in the list payload, both
      asserted.
- [x] **Usage is counted per person** (ADR-048), over 7, 30, 90 or 180 days, defaulting
      to 30, in its own sub-tab with a CSV download and pagination. The three ways a run
      goes wrong are counted **apart** — failed, held, re-run — because they have
      different causes and different fixes, and a single "problems" number would hide the
      only thing worth knowing.
- [x] **Rates are read against the deployment's own average**, and a row under five runs
      is never flagged. *Twice everyone else* is actionable; a score out of a hundred is
      not.
- [x] **A count opens the runs behind it.** `GET /runs?submitted_by=` takes an account id
      rather than a name, because two people can share a display name. The user app gained
      the matching filter, a chip saying whose runs it is showing, and a search that
      covers the submitter.
- [x] **A timezone bug found on the way.** The value report's tests took "today" from the
      local clock while runs are stamped in UTC, so they failed for anybody west of
      Greenwich after their evening crossed UTC midnight — and the same mistake would
      have under-counted a real report. Both now count UTC days.

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

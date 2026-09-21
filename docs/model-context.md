# What reaches the model, and what code decides

**Last derived from the call sites:** 2026-09-21 (Phase 6.14c, extended in 6.14i, 6.15 and 6.21).

An administrator cannot see a prompt. Everything they know about where their words end
up comes from the label next to the box they typed them in, which makes that label the
only account they get — and a console that says a field is background when it now
decides something is worse than a console that says nothing.

This file is the register those labels quote. It is derived from the call sites, not
from memory: every row names the function that puts the value into a prompt or compares
it, so it can be checked rather than believed.

**It changes in the same commit as the code.** `CLAUDE.md` carries that as a standing
touchpoint: a commit that changes what reaches the model, what a stage reads, or a cap
updates this file, the field's marker in both apps, and the training documents, in that
commit.

## The six things a field can do

Both apps mark every field a person can write with one of these. A marker is a fact
about the run rather than help text, so `ui.tooltips` never hides one. The single
exception is the setup marker, which an administrator may switch off because it says a
field is *not* read during a run and so cannot mislead anybody about where their words
go (ADR-046); the four that say where words **do** go cannot be switched off at all. Somebody writing a note deserves to
know whether they are teaching the model, feeding a comparison, leaving a message for
the next reviewer, or writing to themselves.

| Marker | What it means |
| --- | --- |
| **Helps the AI** | Rendered into the prompt as background. Better context here means better findings; it never makes anything pass or fail. |
| **Checked by code** | Compared against the artifacts by code. It can produce a finding, and the same inputs always give the same answer. |
| **Read by a person** | Shown to whoever reviews or signs off the run. Nothing automated acts on it. |
| **Your own note** | Kept with the run for you and anyone looking later. Reaches no model and no check. |
| **Identifies the run** | How the run is found, grouped, and compared with earlier ones — and checked against what the uploaded files declare. |
| **Used for setup, not for runs** | The AI reads it while somebody sets the product up; no validation run reads it. What is built from it is what reaches a run. **The one marker an administrator can switch off** (`ui.setup_markers`, on by default) — ADR-046. |

## The one rule everything here obeys

**The model reads and judges meaning. Code does every comparison** (ADR-001). Nothing in
this register lets a person make the model compare, compute or decide. A field that
reaches the model can change what it pays attention to; it can never make a finding.
Findings come from code evaluating a rule, and rules live in the rule tables.

## Fields that reach the model

All of these are assembled by `pipeline/guidance.py::preamble`, which labels the whole
block *"Context, which is background rather than a requirement. Requirements come only
from the document itself."* If nothing is configured it returns an empty string and the
prompts are byte-for-byte what they were before any of this existed.

| Field | Where it is written | Reaches | Cap |
| --- | --- | --- | --- |
| Artifact type **AI context** | Admin → Artifact types | The prompt for that artifact only: OSL at stage 2, configuration at stage 3 and 4, a report type at stage 8 | 1,500 characters |
| Programme **standing instructions** | Admin → Delivery programmes | Every stage that builds a preamble, on runs in that programme | 1,500 characters |
| **Configuration notes** | User → Configurations, or Admin | Every stage that builds a preamble, on runs of that configuration (ADR-024) | 1,500 characters each |
| **Delivery notes** | The new-run form | Every stage that builds a preamble, on that run | 1,500 characters |
| Programme **scope label** and counts | Admin → Delivery programmes; the new-run form | Every stage that builds a preamble | — |
| **Validation guides** | Admin → Artifact types → Guide | Stages 4 and 8, as a separate block (`guide_block`) | — |
| **Meaning entries** | Admin → Meaning | Stages 4 and 8, through the guide block | — |
| **Programme rules** | Admin → Delivery programmes | Stage 8, with their strictness — which the model states and **code** grades | — |
| **Worked examples** | Admin → Examples | Extraction, description, tracing, judgment, classification, synthesis (ADR-038) | 4 per stage |
| **Judgment check named values** | Admin → Checks | Stage 7, as `name = value` lines for the named values that check lists | — |
| **Attribute statistics** | Read from the delivery's own DIRT | Stage 7, only when `anomaly.model_reads_shape` is on: aggregates per attribute, never a row (Phase 6.21c) | 60 attributes |
| **Artifact type layout map** | Admin → Artifact types → Layout | Only when four deterministic rungs have already failed: the *names* an artifact carries are shown so the model can say which is which (Phase 6.21a) | 80 names |

**The stages that build a preamble** are 2 (extract), 3 (describe), 4 (trace),
6 (reverse), 7 (reports), 8 (verify) and 9 (summarize). Stage 5 (compare) builds none
and makes no model call at all: it is pure comparison, which is ADR-001 visible in a
stage log.

Stage 6 joined that list in Phase 6.15 and is the narrowest case in the product: it
asks the model *where a compliance control is implemented, if anywhere*, and only
when the deterministic matcher has already failed. It never asks whether a delivery
is compliant. Code checks the answer against the paths it offered, applies a
confidence floor, and a located control becomes a review-severity finding for a
person to confirm — never a pass.

**Phase 6.21c added one more, and it is the only call in the product that happens on
every run when it is switched on** — which is exactly why it ships **off**
(`anomaly.model_reads_shape`). The model is shown this delivery's aggregate statistics
— per attribute, how often the value was missing, the smallest and largest, and the
average — and asked which look unusual. Never a row, never an individual value
(ADR-003). It is not asked whether the delivery is correct, whether a requirement is
met, or how serious anything is. Code checks every attribute it names was one it was
shown, applies a confidence floor, and raises a **review** item — a question for a
person, never a failure. The half of that check that runs by default makes no model
call at all: it compares the delivery with the previous finalized deliveries of the
same configuration, in arithmetic.

**Phase 6.21a added a third, and it is the narrowest of them all.** Wherever the tool
looks for a sheet, a column or a row label and four deterministic rungs have failed, the
*names* that artifact carries go to the model once and it says which one was meant. It
is never shown a cell, a row or a number — names only (ADR-003) — and it is never asked
whether anything is correct. Code checks the answer was one of the names it offered,
applies a confidence floor, and the check then runs against that name **and** raises a
`layout_reasoned` review finding, so a reviewer can disagree with the reading rather
than only with the finding. Accepting the reading onto the artifact type's layout map
removes the call from every later run (ADR-051). The same call breaks a tie in artifact
type detection, where it can only choose between candidates code already shortlisted
(Phase 6.21e).

**Stage 7 gained a second one in Phase 6.18f, built to the same shape.** When the
keyword check finds none of the declared programme's words, the delivery's own words
go to the model once, and it says which of the listed programmes they read like. It is
never asked whether the submitter was right: that is a comparison, and code makes it.
Code checks the answer names a programme it offered, applies a confidence floor, and
then decides — the model agreeing with the declaration **softens** a high-severity
finding to a question and never erases it, and the words it quoted are offered to an
administrator as keywords, never applied (ADR-045). What the model is shown is the
delivery's own text, capped, and never a data row (ADR-003).

**The whole preamble is capped at 6,000 characters** (`MAX_BLOCK_CHARS`). Past it the
block is trimmed as a whole and the model is told what was left out — before 6.11e each
field was capped alone, so ten configuration notes were ten times the cap.

**Every one of these is part of the cache key**, because the cache key is a hash of what
was actually sent (ADR-005). Editing guidance therefore refreshes exactly the calls it
changes, and nothing else, without anyone remembering to bump a version.

## Fields code evaluates

These never reach a prompt. Code compares them against the artifacts, and each can
produce a finding.

| Field | Where it is written | Evaluated by |
| --- | --- | --- |
| **Expression checks** | Admin → Checks | `checks/expressions.py` at stage 7 |
| **Field constraints** | Admin → Rules | `checks/field_constraints.py` at stage 7 |
| **Compliance rules** | Admin → Compliance | `checks/compliance_match.py` in code; when that finds nothing, `pipeline/s6_reverse.py` asks the model where the control is and code decides what the answer means |
| **Programme rule strictness** | Admin → Delivery programmes | `pipeline/s8_verify.py` — the model says whether it holds, code sets the severity |
| **Named values** | Admin → Artifact types | `checks/named_values.py`, resolved against the report |
| **Attribute aliases** | Admin → Reference data | `rules/normalize.py`, applied at stages 4, 5 and 7 |
| **Masked columns** | Admin → Reference data | `parsers/masking.py`, at parse time (ADR-003) |
| **Anomaly sensitivity and history** | Admin → Settings → Anomalies | `checks/anomaly.py` at stage 7, against the configuration's previous finalized deliveries. No model (Phase 6.21c) |
| **Submitted identity** | The new-run form | `checks/artifact_match.py`, before any model call (ADR-041) |
| **Credit date** | The new-run form | `checks/artifact_match.py` before the run starts, against the cell `checks/field_labels.py` resolves; `pipeline/s7_reports.py` for whatever the pre-flight did not reach |
| **Field labels** | Admin → Reference data | `checks/field_labels.py`, resolving what a delivery calls a checked field |
| **Artifact type layout map** | Admin → Artifact types → Layout | `resolve/ladder.py`, as the fourth rung — an administrator's spelling resolves a name in code and costs no call (ADR-051) |
| **Scheduled notices** | Admin → Settings → Notices | Nothing evaluates them; they are shown to people between their start and end (Phase 6.14g) |
| **Cost per million tokens** | Admin → Settings → Availability | `spend.py`, over the `llm_calls` rows already stored. Reaches no prompt and refuses nothing: the per-run token budget stays the only hard stop (Phase 6.21d) |

## Fields that are reference only

| Field | What it is for |
| --- | --- |
| Artifact type **description** | Read by the person uploading the file. Reaches nothing. |
| **Artifact samples** | Specimens other definitions resolve against: workbook type detection, named values, guide examples, and the mapping interview. **No sample is opened during a validation run** — `grep sample src/greenlight_ai/pipeline/` finds only ADR-003 comments, and nothing under `pipeline/` can reach `ArtifactSample`. The model reads a sample's layout in one place only: the mapping interview (`meaning/interview.py`), which is a setup activity an administrator starts by hand. **One value does travel**: where a guide entry's locator resolves on a sample, that cell's value is stored on the entry and quoted to the model as `e.g. label=value` at stages 4 and 8 (`checks/guides.py::guide_lines`). It is a single named value an administrator chose, not a row, and it is why samples must be synthetic (ADR-003). |
| Sample **notes** | Read by the model during the mapping interview for that scope, not during a run. |
| **Programme keywords** | Compared by code at stage 7 to confirm a run is the programme it claims. **They no longer only reach code:** when none of the declared programme's words match, the delivery's own words go to the model once, which says what programme they read like (Phase 6.18f). The keywords themselves are not sent — what they decide is *whether the call happens at all*. |
| Programme **name** | Sent with the programme list in that one prompt, because a code on its own says nothing about what a programme is. |

## What never reaches a prompt, under any setting

**No sample row, and no personal data** (ADR-003). The tripwire scans every assembled
prompt and refuses to send a match; `LLM_LOG_PROMPTS` stays false. Where the model is
shown a report's shape — in the mapping interview — it is shown *labels and addresses,
never values*: `meaning/interview.py::_cells_text` says so in its docstring and is
tested for it.

## Checking this file against the code

```bash
# Every place a preamble is built:
grep -rn "preamble(" --include="*.py" src/greenlight_ai/pipeline/

# Every place a sample is read (should never be under pipeline/):
grep -rn "sample" --include="*.py" src/greenlight_ai/pipeline/

# The caps, and what a console can show is left of them (Phase 6.17b):
grep -n "MAX_CONTEXT_CHARS\|MAX_BLOCK_CHARS" src/greenlight_ai/pipeline/guidance.py
grep -n "def budget" src/greenlight_ai/pipeline/guidance.py
grep -n "MAX_PER_STAGE" src/greenlight_ai/llm/examples.py

# Every stage that makes a model call at all:
grep -rn "\.complete(" --include="*.py" src/greenlight_ai/pipeline/
```

**The caps count down rather than merely being stated** (Phase 6.17b).
`GET /admin/prompt-budget` reports what a programme's and a configuration's context
already spends of the 6,000, measured over the same lines `preamble` renders and
counted the way the trimmer counts them, so a field can say what is *left*.

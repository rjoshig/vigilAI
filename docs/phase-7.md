# Phase 7 — Real-world fit

**Status:** ⬜ **not started** · **dormant by design.**

**This phase does not run until the user explicitly asks for it.** Nothing here is
scheduled, and no other phase depends on it. A session that notices this document
should not act on it.

**Goal:** turn a tool that works on invented data into one that works on the customer's
actual files. Every layout assumption in the codebase today came from
`scripts/generate_fixtures.py`, which is a guess. This phase replaces those guesses with
what the real OSL, the real config, and the real reports actually contain, and updates
the documentation to match.

**Where it runs:** a different machine — the one that holds the real files. It never
runs here, because the real files must never reach this repository.

---

## The one rule

> **A real customer file, or anything derived from one, never enters the repository.**
> Not as a fixture, not as a test, not in a commit message, not pasted into an issue,
> not quoted in an ADR. This is ADR-003 and it does not bend for convenience.

What may come back out of this phase:

| May be committed | Must never be committed |
| --- | --- |
| Shapes: sheet names, column headers, heading structures, JSON key names | Any cell value, any row, any consumer record |
| Counts: how many sections, how many attributes, typical row counts | Customer names, order numbers, account identifiers |
| Patterns: date formats, number formats, naming conventions | Anything copied from a file, even one line |
| Synthetic fixtures *modelled on* a real shape | The real file, renamed or truncated |
| Prose describing what a layout looks like | A screenshot of a real file |

When in doubt, describe it instead of copying it. "The DIRT summary sheet has a
label column and a value column, and the total is on the row labelled `Total rows`"
is a shape. The row itself is not.

`.gitignore` blocks `*.docx` and `*.xlsx` outside `tests/fixtures/` as a backstop.
**Check it is still in force before the first file lands on that machine**, and keep the
real files outside the working tree entirely — a sibling directory such as
`../vigilai-real/` — so no accident can stage them.

---

## How to invoke it

The intended interaction is conversational and one artifact at a time:

> "Look at `../vigilai-real/osl-acme-q3.docx` and tell me what needs to change."

Claude should then do the whole loop below without further prompting, and **stop at the
proposal**. It applies nothing until the user says so.

Other phrasings that mean the same thing: *"here is a real config, what breaks?"*,
*"review this report against our parser"*, *"we got the real DIRT, what now?"*

### What Claude does, every time

1. **Read the file with the existing parser** and report what came back: sections found,
   blocks split, sheets and headers read, values resolved. Start from what the tool
   already does rather than from a blank page.
2. **Name the gaps.** Where the parser returned nothing, returned the wrong thing, or
   guessed. Be specific: "section 4.2 has a two-column table where the fixture assumed
   three, so every criterion in it was dropped" beats "the table parsing needs work".
3. **Say what changes, where, and why.** File and function, the nature of the change,
   and what it costs. Distinguish:
   - **Must change** — the tool is wrong or blind without it.
   - **Should change** — it works but will mislead or annoy a reviewer.
   - **Could change** — an improvement worth noting, not worth doing now.
4. **Say what does *not* change**, and briefly why. This is as useful as the gap list:
   it tells the user which of their worries are already handled.
5. **Propose the synthetic fixture** that would lock the new behaviour in — described,
   not written, until the user agrees.
6. **Stop.** Present the proposal and wait.

Only on an explicit go-ahead: make the change, add the fixture, run every gate, update
the affected docs in the same commit, and report what moved.

### The working agreement

- **Propose before changing.** Always. The user has the file; Claude does not have
  context the user lacks.
- **Never guess at a layout.** If one real file is ambiguous, say what would settle it
  and ask for a second example rather than inventing a rule from one sample.
- **One artifact at a time.** An OSL and a DIRT in the same conversation produce a
  muddled proposal.
- **Quote structure, never content.** In the proposal, in the commit, in the ADR.
- **Every change gets a synthetic fixture** mirroring the real shape, or it is not done.
  A parser change with no fixture is a change nobody can defend six months later.

---

## What to look at, per artifact

These lists come from what the code actually assumes today. They are the questions
worth asking of each real file, and each one names the assumption that would break.

### The OSL (`.docx`) · `parsers/osl_docx.py`

| Look at | Today's assumption | Breaks if |
| --- | --- | --- |
| Heading styles | Word `Heading 1..N` styles carry the structure | Sections are bold body text, or a numbered list, or a custom style |
| Section numbering | A leading `3` / `3.1` / `3.1.2` before the heading text | Numbering is in a separate run, auto-numbered by Word, or absent |
| Criteria tables | One header row, uniform column count | Merged cells, multi-row headers, a key/value layout, nested tables |
| Requirement prose | Requirements live in paragraphs and tables under a heading | They live in footnotes, comments, text boxes, or an appendix |
| Attribute lists | A numbered or bulleted list of field names | A table, a comma-run in a sentence, or an attached spreadsheet |
| Revision markers | None expected | Tracked changes or comments carry live requirements |

Also worth reporting: how many sections, how long the longest one is (it becomes one
prompt), and whether any section would exceed a sensible prompt size.

### The ETL config (`.json`) · `parsers/config_json.py`

| Look at | Today's assumption | Breaks if |
| --- | --- | --- |
| Top-level shape | A JSON object with `configuration_id` | It is an array, or the id lives elsewhere or is absent |
| Block boundaries | `filters[]`, `rules{}`, `suppressions{}` split one decision each | Rules nest deeper, or one block holds several unrelated decisions |
| Technical keys | `source`, `sink`, `logging`, `schedule`, `retry`, `runtime` are plumbing | Plumbing uses different names, or a "technical" key carries a business rule |
| Threshold spelling | `min` / `max` / `value` alongside an `op` | Thresholds are strings, ranges, or expressions |
| Field naming | Report-style names such as `SCORE_V3` | An internal code list needing the alias table |
| Waterfall steps | `pipeline.steps[]` as an ordered list of names | Order is implicit, or expressed as dependencies |

Report how many blocks a real config produces. Each non-technical block is one model
call in stage 3, so this is the main driver of cost per run.

### The reports (`.xlsx`) · `parsers/reports/xlsx.py`

Per report type, and there may be types the tool does not know yet:

| Look at | Today's assumption | Breaks if |
| --- | --- | --- |
| Sheet names | `Summary`, `Attributes`, `Sample`, `States`, `Fields`, `Flow` | They are named anything else — likely, and cheap to fix |
| Header row | Row 1 holds the headers | There is a title block, a logo, or merged cells above it |
| Attribute stats | Columns named `Attribute`, `Min`, `Max`, `Nulls` | Different names, transposed layout, or stats on a separate sheet |
| The waterfall | Rows labelled `Accepts`, `Rejects`, `Input` in a `Flow` sheet | Step names differ, or totals are computed rather than stated |
| Identifying columns | The shipped masked-column patterns cover them | A column called `MEMBER_REF` or `HOUSEHOLD_ID` that nothing masks |
| Size | Sheets fit the 100,000-row cap | A DIRT ships every delivered row |

**Masking is the urgent one.** Walk every column header in the real DIRT and decide,
explicitly, whether each is identifying. Anything missed is a value that reaches a
finding, a report, and a prompt. This is the single highest-risk item in the phase.

---

## Where the changes will land

Expected, in rough order of likelihood. The point of the Protocols (ADR-006) is that
the first group absorbs most of the change and nothing downstream moves.

| Where | What changes | Notes |
| --- | --- | --- |
| `parsers/*` | Heading detection, block splitting, sheet and header names | The intended landing zone. Keep the Protocols; the pipeline must not notice |
| Admin data | Masked columns, attribute aliases, named values, artifact types and their AI context, delivery programmes | Data, not code. Seed through the admin-ui or a script |
| `llm/prompts/*` | Worked examples rewritten to match real wording | **Bump the prompt version** — it is part of the cache key (ADR-005) |
| `checks/reports.py` | Sheet and column names the fixed report checks look for | Constants at the top of the module are deliberately in one place |
| `rules/normalize.py` | Number and date formats, state spellings | Only if the real files use forms the parser does not read |
| `tests/fixtures/` | A synthetic case mirroring each real layout's shape | Generated by `scripts/generate_fixtures.py`, never copied |
| `docs/*` | Every assumption this phase disproves | Same commit as the code, per CLAUDE.md |

**A change that reaches `pipeline/` or `rules/schema.py` is a signal.** Those layers are
meant to be layout-independent. If a real file forces a change there, say so explicitly
and explain why, because it means a design assumption was wrong rather than a parsing
detail.

---

## Scope · ⬜ not started

**Bootstrap on the new machine** · ⬜ not started
- [ ] Clone the repo, `pyenv local 3.10.14`, `python -m venv .venv`,
      `pip install -e ".[dev]"`, and confirm `pytest` is green before touching anything.
      A failing baseline makes every later result meaningless.
- [ ] `cp .env.example .env`; leave `DATABASE_URL` on SQLite (ADR-017) unless several
      workers are needed.
- [ ] Confirm `.gitignore` still blocks `*.docx` / `*.xlsx` outside `tests/fixtures/`.
- [ ] Put the real files **outside** the working tree, e.g. `../vigilai-real/`.
- [ ] Point `LLM_*` at the available model and run
      `python scripts/golden_set.py --provider <provider> --out docs/benchmarks/phase-2.md`
      to get a baseline before any prompt changes. This also closes Phase 2 criterion 2.

**Inspection tooling** · ⬜ not started
- [ ] `scripts/inspect_real.py`: read a real file with the production parsers and print
      **only its shape** — sheet names, header rows, section headings, JSON key paths,
      counts, and detected value *formats*. Never a cell value. Its output is safe to
      paste into a conversation, which is the whole point: it is how a real file gets
      discussed without being shared.
- [ ] A `--redact-check` mode that scans its own output with
      `vigilai/llm/tripwire.py` before printing, so the tool cannot leak through the
      thing built to prevent leaks.

**Per-artifact fit** · ⬜ not started
- [ ] OSL: parser adapted, a synthetic fixture mirroring its shape added, extraction
      prompt examples rewritten and the prompt version bumped.
- [ ] Config: block splitting adapted, technical-key list corrected, fixture added.
- [ ] Reports: one pass per report type — sheet and header names, attribute statistics,
      the waterfall layout — with a fixture each.
- [ ] Masked columns: every identifying column in the real DIRT enumerated and loaded.
- [ ] Aliases: seeded from the data dictionary, or from the field names the first runs
      fail to resolve.
- [ ] Named values and checks: the real cell locations behind the admin checks.

**Validation** · ⬜ not started
- [ ] A real set runs end to end and a person who knows the delivery agrees with the
      findings. Disagreements are the real output of this phase: each one is either a
      tool defect or a requirement the tool never knew about.
- [ ] Golden set re-run after the prompt changes; accuracy compared with the baseline.
      **A drop is a blocker**, not a footnote.
- [ ] False positives from the first ten real runs triaged: tool defect, missing
      reference data, or a genuinely ambiguous requirement.

**Documentation** · ⬜ not started
- [ ] Every assumption this phase disproves corrected in `design.md`,
      `architecture.md`, and the phase docs — in the same commit as the code.
- [ ] An ADR per structural surprise: something the design did not anticipate, what was
      done, and what it costs. These are the most valuable records the project will have.
- [ ] `docs/real-world-notes.md`: the shape of each real artifact, in prose. The
      reference for the next person, and the reason no real file needs to be kept.

---

## Acceptance criteria · ⬜ not started

1. [ ] A real OSL, config, and report set runs end to end, and a person who knows the
   delivery agrees with the findings.
2. [ ] Golden-set accuracy after the prompt changes is recorded and is no worse than
   the baseline taken during bootstrap.
3. [ ] Every identifying column in the real DIRT is masked, verified by reading a
   finding's evidence and a generated report and finding nothing identifying.
4. [ ] `git log` and `git diff` over the whole phase contain no real file content.
   Check this explicitly before the first push from that machine.
5. [ ] Every change to a parser is covered by a synthetic fixture mirroring the real
   shape.
6. [ ] The docs describe the real layouts, and no doc still describes a fixture
   assumption that has been disproved.

---

## Out of scope

New features. This phase makes the existing tool correct against real data; it does not
add capability. A real file that reveals a *missing* capability produces a
`# SPEC GAP:` and a conversation, not an unplanned feature.

Also out of scope: anything the platform or compliance teams own (TLS, encrypted
volumes, retention sign-off). Those are Phase 6's in-house items and stay there.

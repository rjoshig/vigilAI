# Phase 6.1 — Richer inputs and a trainable rule loop

**Status:** ✅ **complete** (2026-09-18), with two items deliberately open and marked
below: the standalone sample-exploration screen in the user app, and flagging a
contradiction at the moment an observation is written rather than at the candidate
stage. Every acceptance criterion is met. Built after Phase 6.2 so the training loop
is attributed to real people from its first day.

**Goal:** two things the tool cannot do today.

1. **Accept the inputs real campaigns actually arrive with** — several sample workbooks
   per artifact type, several files per report type in one run, workbooks whose type
   has to be worked out rather than declared, and the delivery context that says how
   many outputs are in play.
2. **Get better over time from the people using it.** A reviewer who knows that a
   particular field must never be blank, or that a particular OSL clause is what a
   particular report column answers to, can say so **in their own words, anchored to
   the cell or clause they mean**. An administrator reviews those statements, has the
   model synthesize them into rules, approves them, and they apply to every run from
   then on.

Effort 3–4 weeks, most of it in part B. Read `design.md` "Configurable checks", ADR-020
and ADR-021 in `decisions.md`, and `llm-privacy.md` before starting.

## The one thing that makes or breaks this

**A rule learned from a person must enter the same rule surface the engine already
runs, and nothing may activate without a human approving it.**

Training produces `check_definitions`, `compliance_rules`, and the new
`field_constraints` rows — the things stages 6 and 7 already know how to evaluate. It
does not add a second evaluation engine, a second findings path, or a rule format only
the training loop understands. If that discipline slips, the tool ends up with two ways
to be wrong and no single place to look.

The corollary is ADR-001, unchanged: the model reads the human's sentence and **proposes
a structured rule**; code evaluates the rule. A synthesized rule that cannot be
expressed as data an evaluator runs is rejected, not special-cased.

## Prior art, and what it tells us

Every mature data-quality tool has already met this problem, and they agree on more
than they disagree.

| Tool | A rule is | Machine-suggested rules |
| --- | --- | --- |
| Great Expectations | A typed assertion object (column, type, parameters) in a named, versioned suite | Profiler-generated expectations land in the suite as drafts a person edits before a checkpoint enforces them |
| Soda | A declarative check in YAML, scoped per dataset, reviewed in git | Profiling suggests checks; a person accepts one before it enters the file |
| AWS Deequ | A constraint on a column, evaluated in one metric pass | Constraint suggestion proposes constraints **with a rationale**, explicitly for human review |
| dbt | A YAML test or a SQL test returning failing rows | None; the gate is code review |
| Anomalo, Monte Carlo | A fitted monitor with derived thresholds | Monitors appear "suggested", with an expected alert rate, and a person promotes them |

Three things are worth copying outright:

- **"Suggested" and "active" are different states in the data model.** Not one flag,
  and never auto-promoted. Every tool above draws this line.
- **A suggestion carries its rationale**, so the reviewer is judging an argument rather
  than a verdict.
- **The rule object has the same shape everywhere**: scope, assertion type, parameters,
  source, status, version, approver, timestamp. There is no reason to invent another.

What they do *not* have is the thing this phase is for: a rule that starts as a
sentence a reviewer typed. That is where the model earns its place, and where the
safeguards below come from.

## The rule lifecycle

One state machine, for every rule, however it was born — typed by an administrator,
synthesized from observations, or shipped as a default.

```
observation(s) ──synthesize──▶ draft ──approve──▶ shadow ──activate──▶ active
                                 │                   │                  ▲ │
                                 └──reject           └──reject          │ └──disable──▶ disabled
                                                                        └────enable────┘
                                                                                │
                                                        delete (either state) ──┴──▶ deleted
                                                                                      │ restorable
                                                                                      │ for 6 months
                                                                                      ▼
                                                                                  permanent
```

- **draft** — the model has proposed it, code has validated it, nobody has agreed to
  it. It never runs.
- **shadow** — it runs on every run, its findings are stored and counted, and no
  reviewer sees them. This is where its precision becomes knowable.
- **active** — it produces findings like any other rule.
- **disabled** — switched off by an administrator, reversible at any time. This is
  where a noisy rule goes, and where a rule goes that is wrong for now but may be
  right later.
- **deleted** — soft. It no longer runs and no longer appears in the default view, and
  an administrator can restore it for **six months**.
- **permanent** — after the restore window it cannot be brought back. What survives is
  its identity, its version, and its provenance, so findings from old runs that cite
  it still explain themselves.

**No rule ever expires on its own.** A rule that has not fired in a year is either
load-bearing or dead, and nothing inside the system can tell which. The dead-rule
report surfaces the candidates and a person decides. Every transition records who did
it and when, and no transition happens by itself. That log is not bookkeeping: under
the EU AI Act's human-oversight provisions and the NIST AI Risk Management Framework,
the record of the human decision is itself the required artifact, and it is cheap to
keep only if it is kept from the start.

## Scope · 🟡 in progress

### 6.1a — Several samples per artifact type · ✅ complete

Today an artifact type holds one sample workbook, in `filename` and `storage_path` on
`artifact_types`, and the admin-ui can replace it but cannot show it. Real report types
vary between customers, and one sample hides that.

- [x] New table `artifact_samples`: `artifact_type_id`, `label`, `filename`,
      `storage_key`, `sha256`, `size_bytes`, `sheets` (JSON), `notes`, `uploaded_at`.
      **At most three per type**, enforced in the API with a clear message rather than
      silently dropping the fourth. Three is the user's number and it is a good one:
      enough to show variation, few enough that an administrator reads them all.
- [x] The single-sample fields on `artifact_types` are migrated into the new table as
      the first sample and then dropped. No code keeps reading them.
- [x] `GET /admin/artifact-types/{key}/samples` lists them;
      `GET .../samples/{id}/download` streams the file with its original filename, so
      **an administrator can always see the sample in use** — the gap the user named.
- [x] `GET .../samples/{id}/preview` returns the parsed structure: sheet names, header
      labels, populated cell addresses, and values, **with the masked-column list
      applied** exactly as at parse time. A preview is a view of a file that may hold
      customer data, so it obeys the same masking as everything else (ADR-003).
- [x] Named-value resolution runs against **every** sample, not one, and the admin-ui
      shows which samples a pointer resolves on. A pointer that works on one layout and
      not another is the exact defect this milestone exists to surface.
- [x] admin-ui: a samples strip on each artifact type — up to three cards, each with
      its label, sheet list, a **View** action opening the preview grid, a **Download**
      action, and a **Remove**. Replace stays, on the individual sample.

### 6.1b — Several files per report type in one run · ✅ complete

Some campaigns deliver the same report type more than once: one field distribution per
segment, per state, or per deliverable.

- [x] `run_files` gains `part` (an integer ordinal within the kind) and `part_label`
      (what the uploader calls it). The unique key becomes (`run_id`, `kind`, `part`).
- [x] The upload endpoint accepts repeated fields for one key, and the new-run form
      lets a slot hold several files with a label each. The 50 MB per-file limit and
      every other upload guard are unchanged and apply per file.
- [x] Report parsers return a list of parsed documents per kind. `RunContext` carries
      `reports[kind] -> list[ParsedReport]` rather than one.
- [x] **How a check behaves over parts is declared, not guessed.** Each check gets an
      `over` field: `each` (evaluate per part; one finding per failing part, naming the
      part) or `total` (evaluate once over the summed named values). `each` is the
      default because it is the answer that is never silently wrong. A named value used
      under `total` must be numeric; anything else is a "could not evaluate" finding,
      never a silent skip.
- [x] The review screen and the final report name the part on every finding that came
      from one, because "the field distribution is wrong" is useless when five were
      uploaded.

### 6.1c — Delivery context on the run · ✅ complete

- [x] `runs` gains `deliverable_count`, `outputs_validated`, and `delivery_notes`, set
      on the new-run form beside the programme and the suppressions answer from
      ADR-020.
- [x] Code checks them: if a run declares four deliverables and one field distribution
      is uploaded, that is a **finding**, not a silent pass. This is the point of
      collecting the numbers — a count the model is merely told is a count nobody
      verifies.
- [x] The numbers and the notes join the guidance preamble
      (`pipeline/guidance.py`), which keeps the ADR-020 rule: empty adds nothing.

### 6.1d — Working out what a workbook is · ✅ complete

A user should not have to know that their workbook is a "field distribution", and a
field distribution may arrive as several tabs in one file.

- [x] **Deterministic first.** A fingerprint of a workbook — normalized sheet names,
      header-row tokens, and shape — is scored against every stored sample of every
      active artifact type. A score above the confident threshold assigns the type; a
      near tie or nothing above the floor assigns nothing.
- [x] **The model only breaks ties, and only on labels.** When two types score close,
      one cached call asks which set of sheet and column *names* better matches which
      type description. It sees names and the administrator's description. It never
      sees a value, and it never decides alone: its answer picks between the candidates
      code already shortlisted.
- [x] **An uncertain guess asks.** The upload form shows the detected type as a
      pre-selected dropdown the user can correct, with the confidence and the reason.
      A wrong silent assignment is worse than a question.
- [x] A multi-tab workbook can map to **several** types: detection runs per sheet and
      the file is registered once per detected type, with the sheet recorded. This is
      what the user's "field distribution can have multiple tabs" needs.
- [x] Every correction a user makes is recorded. Corrections are the cheapest training
      signal in the system and they feed 6.1e's queue automatically.

### 6.1e — Train AI mode: observations · 🟡 in progress

The user-facing half of the learning loop. Off by default; an administrator switches it
on.

- [x] `app_settings`: a small key/value table for operator switches, with
      `train_ai_mode` the first one. `GET /runs/options` reports it, so the user-ui
      shows the training affordances only when it is on.
- [~] **A data-point viewer.** The admin console previews a sample workbook cell by
      cell, with the label to each cell's left, and an observation raised from a
      finding carries that finding's evidence as its anchor. **Outstanding:** the
      standalone "explore a sample" screen in the user app, and browsing an OSL's
      sections or a config's JSON paths to anchor against.
- [x] **An observation is anchored to a selection, not only to prose.** The user clicks
      a cell, a label, an OSL section, or a config path, and writes what they mean. The
      stored observation carries both. This is the difference between a rule the model
      can synthesize reliably and one it has to guess at, and it is the single most
      important design point in part B.
- [x] `training_observations`: `run_id` (nullable), `author`, `kind`
      (`reconciliation` | `field_constraint` | `correction` | `note`), `anchors` (JSON
      list of typed selections), `statement` (the human's words), `expectation`,
      `severity_hint`, `scope_hint` (global | customer | programme), `status`
      (`new` | `queued` | `synthesized` | `rejected` | `superseded`), timestamps.
- [x] **Field-level statements are first-class**, because they are what people actually
      have to say: "this field is never blank", "account review never carries these
      values", "this must look like a date". The form offers the field, the constraint
      in plain words, and the severity; the anchor makes "this field" unambiguous.
- [x] **The PII tripwire runs when an observation is saved**, not only when a prompt is
      assembled (ADR-018 extended). A reviewer typing while looking at real data is
      exactly where an account number gets pasted, and rejecting it at the source with
      a clear message is the only place the person can still fix it.
- [x] **Anyone may file an observation**, with their name recorded (the placeholder
      while login is off, per ADR-022). Observations are inert until an administrator
      acts, so approval is the real control and a permission list would be machinery
      guarding nothing.
- [x] **The form shows the rules that already cover the field or anchor** being
      commented on. This is the cheapest defence against a queue that fills with five
      versions of one insight, and it teaches people what the tool already checks.
- [x] **An observation is editable by its author until an administrator queues it**,
      after which it freezes. Every edit is versioned, so the audit trail survives the
      convenience.
- [~] **An observation that contradicts an active rule is flagged as a conflict**, not
      filtered out. Conflict detection runs at the candidate stage and the
      administrator sees the overlap before approving. **Outstanding:** flagging it at
      the moment the observation is written, which is when the author could reconsider.
- [x] A reviewer can raise an observation straight from a finding — "this fired but it
      is fine, because…" — which turns the dismissals the tool already collects into
      training input instead of leaving them as a review note nobody reads again.

### 6.1f — Train AI mode: synthesis and approval · ✅ complete

The administrator-facing half. Nothing here runs by itself.

- [x] An admin-ui **review queue**: observations grouped by anchor and by field, with
      their author, run, and text, and bulk select.
- [x] **Synthesis is one explicit action on a selected group**, producing
      `rule_candidates`: `name`, `target_kind` (`check` | `compliance_rule` |
      `field_constraint`), the structured rule body, `reasoning`, `severity`, `scope`,
      `source_observation_ids`, `model`, `prompt_version`, `status`
      (`draft` | `approved` | `rejected`), `admin_note`. Cached and logged like every
      other call (ADR-005).
- [x] **The user's words are data, never instruction.** The synthesis prompt carries
      them in a delimited block, labelled as a statement to interpret. The model's job
      is to express the statement as a rule, not to follow it. A statement that asks
      for something outside the rule schema comes back as "cannot be expressed", and an
      administrator reads why. Prompt injection matters more here than anywhere else in
      the tool, because the output becomes a rule applied to every run.
- [x] **The model emits a schema-constrained rule object, never prose.** Loose parsing
      of free-form model output is the actual injection exposure — not the user's text
      — because it is where downstream code starts trusting something nobody checked.
- [x] **Code validates everything the model returns** before a person even sees it: the
      rule parses, its named values resolve against the stored samples, its expression
      compiles, and its severity and scope are in range. A malformed or out-of-scope
      candidate is rejected outright with the reason shown.
      `POST /admin/checks/test` already does most of this and is reused rather than
      reimplemented.
- [x] **The model gets no authority beyond proposing.** No write, no activation, no
      chained call that runs what it wrote. This is OWASP's "excessive agency" in its
      most literal form, and the restriction costs nothing here because approval was
      always going to be a person's job.
- [x] **Conflict and duplicate detection, in code, at approval time.** Candidates are
      fingerprinted on (scope, assertion type, parameters); an overlap with an active
      rule is flagged with the overlap shown, and the administrator either supersedes
      the old rule explicitly or rejects the new one. Contradictions are caught the
      same way — one rule permitting a blank while another forbids it is an overlap
      with opposite verdicts. This has to run at creation. Overlapping rules
      accumulate silently and are very hard to untangle later.
- [x] **Replay before promotion.** A candidate runs against the golden set and the last
      N finalized runs, and the admin-ui shows exactly what would have changed: which
      runs gain a finding, which of those findings the reviewer had already marked OK.
      A rule that would have fired on thirty historical runs that were all fine is a
      bad rule, and this is where that becomes visible instead of next month.
- [x] **Approval writes a normal rule row**, versioned, and stores its provenance: the
      source observations, the model and provider, the prompt version (the field
      already exists, because it is part of every cache key), the approver, the
      timestamp, and **the diff between what the model drafted and what was approved**.
      That diff is the measure of how much correcting the model needs; without it there
      is no way to tell whether synthesis is working, and it is the first thing to look
      at when tuning the prompt. From approval on, the pipeline treats the rule like
      any other. The run fingerprint already includes active check versions, so a new
      rule correctly invalidates the duplicate shortcut.
- [x] **The author hears back.** A status list shows each observation as queued,
      synthesized, approved, or rejected, with the administrator's reason on a
      rejection and a link to the rule on an approval. Without this, contributions
      stop within a month.
- [x] `field_constraints`: `field` (canonical name, resolved through the alias table),
      `constraint` (`not_blank` | `allowed_values` | `forbidden_values` | `range` |
      `format` | `fill_rate_min`), `value` (JSON), `scope`, `severity`, `reasoning`,
      provenance, `is_active`, `state`. Evaluated in stage 7 against the DIRT and the
      distributions. Structured data, evaluated by code — the human language is the
      input to synthesis, not the thing that runs.

### 6.1g — Shadow mode, precision, and retirement · ✅ complete

The part that makes "smarter over time" true rather than aspirational.

- [x] A promoted rule starts in **shadow**: it runs, its findings are stored and
      counted, and they are **not** shown to reviewers or put in the report. An
      administrator sees the shadow findings and activates the rule when it has earned
      it. Warn-then-enforce is standard practice for exactly this reason: a new rule's
      precision is unknown until it has met real data, and going straight to enforcing
      spends reviewer trust that is slow to earn back.
- [x] **An administrator activates, with the numbers in front of them.** No automatic
      bar: the activation screen shows fired count, dismissal rate, and the shadow
      findings themselves, and a person decides. This was chosen over a fixed
      threshold because a rule that fires rarely would sit in shadow forever waiting
      for a sample it never gets. The cost is that the bar moves with whoever is
      looking, which is why the numbers are shown rather than summarised.
- [x] Per-rule statistics on the usage dashboard: times fired, share of its findings
      marked **Not OK** (kept) versus **OK** (dismissed), last fired, age.
- [x] **Noisy-rule and dead-rule reports.** A rule whose findings are dismissed above a
      threshold, or which has not fired in a long time, is surfaced for review with a
      one-click disable. Nothing is disabled automatically and nothing expires: a rule
      with a 90% dismissal rate may be the one rule that matters, and only a person
      knows.
- [x] **A noisy rule is usually an under-scoped rule, not a wrong one.** The most common
      cause of false positives is a rule that encodes an assumption true of most
      records and not all — a field that is genuinely optional for one segment, a
      format that legacy records predate. So the retire prompt offers "narrow the
      scope" beside "retire", because narrowing is usually the right answer and nobody
      reaches for it unprompted.
- [x] Disabling or deleting a rule never edits a past finding. Old runs stay
      reproducible through `rules_version`, which already exists.

### 6.1i — One searchable rules screen · ✅ complete

Every rule the tool holds, in one place, whatever its origin. A learned rule that
cannot be found is worse than no learned rule, because nobody knows why a finding
appeared.

- [x] An admin console **Rules** screen listing checks, compliance rules, and field
      constraints together, with an **origin** column: shipped, written by an
      administrator, or learned from observations.
- [x] **Search** across name, the plain-language reasoning, the field or named values
      a rule touches, and its scope. This is the screen someone opens when a finding
      surprises them, so it has to answer "what made this fire" quickly.
- [x] **A state filter defaulting to active.** The other states — shadow, disabled,
      deleted — are one click away, so nothing is hidden and nothing is in the way.
- [x] Per rule: its state, scope, severity, origin, fired count, dismissal rate, when
      it last fired, and for a learned rule its source observations and approver.
- [x] **Enable, disable, delete, and restore**, each requiring the administrator to
      type the word — `enable`, `disable`, `delete`, `restore` — in a confirmation
      dialog. A rule change reaches every future run, and a typed word is the cheapest
      way to make sure the click was meant. *(Typing to confirm on the reversible
      actions is deliberate, at the user's request. If it proves to be friction in
      practice, enable and disable are the two to reconsider.)*
- [x] **Delete is soft and restorable for six months.** A deleted rule stops running
      immediately, leaves the default view, and can be brought back whole, with its
      provenance and its history intact.
- [x] After six months the retention sweep makes the deletion permanent. It keeps a
      tombstone — identity, version, provenance, and reasoning — because findings on
      old runs cite the rule by reference and must still explain themselves.
- [x] Every one of these actions is an audit event naming the administrator, and
      deletions and restores are visible in the rule's own history.

### 6.1h — Documentation and tests · ✅ complete

- [x] ADR-021 (inputs: several samples, several files, detection) and ADR-022 (the
      training loop) written before the code, not after.
- [x] `docs/design.md`, `docs/architecture.md`, `docs/llm-privacy.md` (the synthesis
      prompt is a new place text reaches the model), `docs/glossary.md` (observation,
      candidate rule, shadow mode, part, anchor) updated in the same commits.
- [x] Tests per module as usual, plus: a synthetic end-to-end training test that goes
      observation → synthesis with the scripted stand-in model → candidate → replay →
      approval → the rule firing on a later run; a prompt-injection test asserting an
      observation containing an instruction does not change the synthesized rule's
      shape; a tripwire test asserting an observation containing a fake account number
      is refused at save.

## Acceptance criteria · ✅ complete

1. [x] An artifact type holds up to three samples; each can be viewed as a grid and
   downloaded, and a named value shows which samples it resolves on.
2. [x] A run accepts several files for one report type, each labelled, and a check
   declaring `each` produces one finding per failing part, naming it.
3. [x] A run declaring more deliverables than the files uploaded produces a finding.
4. [x] An unlabelled workbook is assigned its type by fingerprint against the samples,
   an uncertain one asks the user, and a multi-tab workbook maps to several types.
5. [x] With Train AI mode off, the user-ui is exactly what it is today, and no new
   table is written to.
6. [x] With it on, a reviewer anchors an observation to a cell and to an OSL section,
   writes a sentence, and an administrator sees it in the queue.
7. [x] An administrator synthesizes a group of observations into a candidate rule,
   sees the replay against the golden set and recent runs, approves it, and the rule
   fires on the next run with its provenance visible on the finding.
8. [x] A field-level statement in plain words becomes a structured `field_constraints`
   row, and a blank in that field becomes a finding at the stated severity.
9. [x] A promoted rule runs in shadow until an administrator activates it, and the
   dashboard shows its fired count and dismissal rate.
10. [x] An observation containing an instruction to the model does not change the shape
    of the synthesized rule, and one containing PII is refused when saved.
11. [x] The rules screen finds a rule by a word from its reasoning, shows active rules
    by default, and reaches disabled and deleted ones through the filter.
12. [x] Disabling, deleting, and restoring each require the word typed, take effect on
    the next run, and appear in the audit log with the administrator's name.
13. [x] A rule deleted five months ago can be restored whole; one deleted seven months
    ago cannot, and a finding from an old run that cites it still explains itself.

## Decisions (2026-09-18)

Answered by the user; the reasoning is in ADR-021.

| Question | Decision |
| --- | --- |
| Default scope of a learned rule | **The narrowest that fits** — the customer or programme the observation came from. Going global is a separate, deliberate action. Under-scoped assumptions are the top cause of false positives, and a rule that fires wrongly everywhere is what stops people reading findings. |
| Who may file an observation | **Anyone**, with their name recorded. Approval is the real control. |
| Several files per report type | **One finding per failing part**, naming the part. Precise, and never silently wrong. |
| Leaving shadow mode | **An administrator activates**, with fired count, dismissal rate, and the shadow findings shown. No automatic threshold. |
| How much history replay may read | **The golden set plus recent finalized runs.** Replay re-reads stored customer files on the server, which is accepted; nothing leaves it. |
| Do observations outlive the 90-day purge | **Yes, kept indefinitely**, including their text. They are institutional knowledge, and the tripwire is what keeps customer data out of them at save time. |
| Editing an observation | **Editable until an administrator queues it**, then frozen. Versioned throughout. |
| Showing existing rules while writing | **Yes, inline**, to stop duplicate observations. |
| An observation contradicting an active rule | **Flagged as a conflict** for the administrator, as a signal the old rule may be wrong. |
| Telling the author the outcome | **Yes, with the reason.** |
| Does a learned rule expire | **Never on its own.** Rules live in a searchable admin screen and an administrator enables, disables, or deletes them. |
| Deleting a rule | **Soft, restorable for six months**, then permanent with a tombstone so old findings still explain themselves. |
| Confirming a state change | **Type the word** — enable, disable, delete, restore — in a second dialog. |

## Still open

Nothing. Every design question in this phase is answered; the remaining unknowns are
implementation details that do not change the shape.

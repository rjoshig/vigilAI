# Session Log

Working journal. **Read the "Resume here" block first at the start of every session; update
it and append an entry at the end.** Required fields per entry: branch, phase, status,
what was completed, what's pending, blockers, next concrete action. No PII, no customer
names, no sample data.

---

## Resume here

| Field | Value |
| --- | --- |
| Phases complete | **0–5**, **6.1–6.4**, **6.6–6.13**; **6 in progress**; **7 dormant** (runs only on request, on the target PC) |
| Branch | `claude/pending-items-review-f35uek`, cut from `main` at the merge of PR #54. **Phases 6.14, 6.15 and 6.16 are complete and merged. 6.17a is measured and repaired** — false high-severity findings from the programme keyword check went from five to one, and the one left is a meaning problem, deferred to 6.18f rather than dropped. **[`phase-6.18.md`](phase-6.18.md) is written and not started:** trust that is earned, measured and revocable — the phase that lets a reviewer stop reading every finding. **Next concrete action: the user reads 6.18 and answers its five open questions** (where a signature lives, how many maturity levels, whether demotion follows scope or configuration, what the minimum evidence for a promotion is, and whether a demoted signature ever returns on its own). Nothing else in 6.17 is blocking |
| Last updated | 2026-09-20 |

**The product is built and works end to end.** Submit an OSL, a config, and the
reports; the worker runs the nine stages; a reviewer decides each finding; the frozen
one-page report is generated once and never regenerated.

### See it running

```bash
source .venv/bin/activate
set -a && . ./.env && set +a   # nothing in src/ loads .env; without this the
                               # worker starts on the built-in defaults and logs
                               # "building mock client (model=gemma3:27b)"
export DATABASE_URL="sqlite+pysqlite:///$PWD/data/demo.db" GREENLIGHT_AI_DATA_DIR="$PWD/data"
python scripts/seed_demo.py          # 8 runs in every lifecycle state + admin data
uvicorn greenlight_ai.api.app:get_app --factory --reload   # :8000
python -m greenlight_ai.worker.app                          # another terminal
cd user-ui && npm run dev                             # :3000
cd admin-ui && npm run dev                            # :3001
```

`scripts/seed_demo.py` loads the aliases, the artifact catalog with five sample
workbooks and one worked example of AI context, the design doc's three example checks,
the compliance rules, and runs sitting at queued, needs review, finalized OK, finalized
Not OK, and failed.

The user-ui sidebar now carries an **Admin console** launcher
(`NEXT_PUBLIC_ADMIN_URL`, default `http://localhost:3001`), so the two apps are one
click apart in development.

**Gates:** `black . --target-version py310 && flake8 && mypy src/ && pytest &&
bash scripts/check_docs.sh`, and in each UI: `npm run lint && npm run typecheck &&
npm run format:check && npm test && npm run build`.

### Phase 7 is written but dormant

[`phase-7.md`](phase-7.md) is the phase for the machine that holds the real files
(ADR-019). It runs **only when you ask**, one artifact at a time: *"look at this OSL and
tell me what needs to change"*. It carries the per-artifact tables of what the parsers
assume today and what would break each assumption, so the analysis starts from the code
rather than a blank page. Its first rule is that no real file, and nothing derived from
one, enters this repository.

### Phase 6.1 is specified and waiting on six answers

[`phase-6.1.md`](phase-6.1.md) covers richer inputs (up to three samples per artifact
type, several files per report type, workbook type detection, delivery counts) and
**Train AI mode**: reviewers record anchored observations in their own words, an
administrator has the model synthesize them into candidate rules, and an approved rule
runs in shadow before it counts. ADR-021 holds the shape and is **proposed**, not
accepted, because six open questions at the foot of the phase doc change the design.
Answer those first.

### What was built on 2026-09-18

Three phases, in this order, all with their gates green.

**6.2, optional login.** Two `.env` switches, both off. With them off the product is
exactly what it was and every action is attributed to a seeded placeholder, John Doe.
With them on, an administrator creates accounts for both roles, everyone changes their
password at first sign-in, and the API refuses to serve a non-loopback deployment
while the bootstrap password stands.

**6.3, runtime settings.** The admin console overrides `.env`, which overrides the
built-in default, for the model, login, throughput, uploads and retention. The console
shows which layer every value came from. The database URL, the data directory, the
bind address and the master key are never editable there, because each is needed to
reach or protect the settings store itself.

**6.1, richer inputs and Train AI mode.** Three samples per artifact type, viewable
and downloadable. Several files per report type, each labelled, with findings naming
the part. A deliverable count that code checks against the files that arrived.
Workbook type detection that asks when unsure. And the training loop: a reviewer's
sentence, anchored to what they meant, becomes a candidate rule the model drafts, code
validates, a replay tests, and a person approves into shadow.

### Outstanding, needs the user

- **A decision on retention for DIRT files** (90 days by default), and **security and
  compliance sign-off** on retention and PII handling. Both are Phase 6 criteria and
  both want an ADR.
- **A local model** or an API key: `python scripts/golden_set.py --provider openai
  --out docs/benchmarks/phase-2.md` closes Phase 2 criterion 2 and Phase 6 criterion 2
  in one command. Expect a prompt-version bump afterwards.
- **A sanitized shape reference** for the real OSL, config, and report layouts. The
  parser Protocols exist so this is the only code that changes, but every layout
  assumption today came from synthetic fixtures.
- **On a machine with Docker:** `docker compose up --build` once (Phase 3 criterion 1).
  This is the last unverified criterion in Phases 0–5.
- Whether a data dictionary exists to seed the alias table from.

---

## Session: 2026-09-20 (6.17a repaired, and 6.18 specified)

**Branch:** `claude/pending-items-review-f35uek` · **Status:** 6.17a repaired, 6.18
written, all gates green at 1443 tests.

**6.17a — the repair.** Two changes, neither of which asks a model anything. ADR-042
records the decision as *match loosely, count strictly*.

*Loosely*: `checks/programme_match.py`, in the shape `compliance_match.py` established.
Three tests, any of which finds a keyword — a normalised substring first, because it
preserves every match the old behaviour made and with it every inflection a substring
caught for free; the keyword's words adjacent after a conservative singular fold; and,
for a multi-word keyword only, its words within a stated window in any order. The fold
removes a plural and nothing else, because a false match here has to be explainable to
the person reading the finding.

*Strictly*: a programme may be named as what a delivery reads like only on words **it
alone claims**, and only when it is strictly ahead of the next programme. A tie is not
an answer. The seeded lists lost `snapshot` and `historical` and gained the words the
business says. The structural guard matters more than the keyword edit: removing two
words fixed one instance, and *a programme is named only on words it alone claims* is
what stops an administrator recreating it with the next overlapping word they add.

The same twenty deliveries re-measured: **4 silent / 11 review / 5 high → 15 silent /
4 review / 1 high**, with the control class unchanged at 3 of 3. The four review items
left are honest — `ITA` for *invitation to apply*, a *legacy history pull* where the
list says `legacy extract` — and an administrator's added word closes each permanently.

The one remaining high is kept as a test and is the worked example for 6.18f: a
*promotional acquisition mailing* that suppresses `existing accounts` has two of
Account Monitoring's words and none of its own. Nothing is misspelled — the words
really are the other programme's, and what makes them innocent is that they appear
under *suppress* and *removes*. No normalising rule reaches meaning.

**6.18 — specified, not started.** Written from the goal the user stated directly: a
reviewer should not have to look at every validation point. It corrects a misreading
this session was itself making — ADR-021 puts a person at the gate of a **rule**, not
of every **finding**, and approving a rule is precisely the act of saying *apply this
without asking me again*. Five scope groups: findings that learn their own severity
from the verdicts people gave; a maturity level an administrator sets deliberately and
can drop instantly; trustworthiness as a dated number that gates any promotion;
nothing hidden without a record, with `high` and above never auto-demoted; and a small
random sample reviewed in full forever, so drift is caught by the tool rather than by
the customer. The one automatic move in the phase is in the safe direction only: **the
tool may revoke its own trust and may never grant it.** The model's own confidence
score is explicitly not a licence to skip anyone — it discards a weak answer today and
never trusts a strong one, and that stays.

**Also corrected:** ADR-042 first cited a non-existent ADR for 6.15's matching work —
there is no ADR covering it, so the reference now points at the phase doc. The admin
console's keyword hint and `admin-training.md` both understated what the field does;
an administrator cannot see a prompt or a matcher, so the hint is the only account they
get of why their word list behaves as it does.

**Pending:** 6.18's five open questions, which want the user; 6.17b (the cap
countdown); 6.17c, where the premise is still factually wrong in the doc and the user
has not yet said whether to correct it; and the two standing touchpoints —
`gd-rollout-plan.md` unread since 6.13, and both training documents still dated *after
Phase 6.14*. The admin document's keyword section is now current; the rest of its
realignment with 6.15 and 6.16 has not been done, so the date is deliberately left as
it was rather than claiming an alignment that did not happen.

**Next concrete action:** the user reads `phase-6.18.md` and answers its open questions.

---

## Session: 2026-09-20 (6.17a — the programme keyword check, measured)

**Branch:** `claude/pending-items-review-f35uek` · **Status:** 6.17a complete, gates green.

The third surface finally got the half-hour measurement the other two had. Seventeen
deliveries, every one genuinely the programme it declared, worded the way another
customer might word it. Four were silent, eleven raised a review item, and **five fired
at HIGH** — a false positive at the highest severity the tool has.

Two defects, and they compound. A phrase keyword needs exact adjacency and exact
plurality, so `existing account` misses `existing accounts` and `invitation-to-apply`
misses `invitation to apply`; that opens the door. Then `snapshot` and `historical` —
two of the four shipped Archives keywords — are ordinary data-delivery vocabulary that
any programme's specification contains, so Archives clears the two-hit floor by accident
and the run is confidently reported as the wrong programme. The knife-edge case is a
realistic prescreen OSL that is silent only because one sentence says `firm offer`:
reword that phrase and the same document is HIGH.

The control class still passes 3 of 3 — a delivery genuinely declared as the wrong
programme is caught every time — so the check is not broken and should not be replaced.
Anything built goes behind it, as 6.15's option C did.

The measurement is kept as `tests/pipeline/test_programme_keyword_brittleness.py`,
mirroring how 6.15 kept its measured failure shapes. Those tests assert what the check
does **today**, not what it should do, so the result cannot drift unnoticed and a fix
has to come past them deliberately.

Also corrected status drift the tables had accumulated: `CLAUDE.md` and
`phase-plan.md` both said 6.14 was not started and `phase-plan.md` said 6.15 was in
progress, while both phase docs said otherwise. `check_docs.sh` does not compare the
two tables against the phase docs, which is how that survived.

**Pending:** a decision on which of 6.17a's four recommendations to build; 6.17b (the
cap countdown); 6.17c, to be **discussed before any code** at the user's request; and
the two standing touchpoints — `gd-rollout-plan.md` unread since 6.13, and both training
documents still saying "after Phase 6.14".

**Next concrete action:** discuss 6.17c with the user, then decide 6.17a's build.

---

## Session: 2026-09-20 (Phase 6.13f and the phase closes)

**Branch:** `feature/loop-closes` · **Status:** phase 6.13 complete, gates green.

The documents the milestones had not already carried. Both training documents say who
Train AI mode is for and what the screens now do: the user document's Train AI section
names the senior-associate audience and keeps the status chain; the administrator's gains
a **Worked examples** section (what an example is, what the console refuses and why, how
promotion works) and a replay that says what it now measures and what it does not claim.
`gd-rollout-plan.md` stage 3 asks the seniors to review shadow findings rather than assume
a dismissal rate, and to add worked examples as they correct the model; its gate says so.

Every acceptance criterion is ticked, each against a test that exists: lens settings reach
the context, two parts are two files, a shadow compliance rule produces a hidden finding
with a reference, the author follows an observation from waiting to live, a finding names
the learned rule behind it, an example is refused unless its answer fits the stage schema,
a judgment verdict becomes what code decides it becomes, and a replay reports the runs it
evaluated. 1222 Python tests, 86 admin-ui, 91 user-ui, golden set 15/15.

**Next:** nothing is started. Phase 6.13 closes here; the next piece of work is the
user's to choose.

---

## Session: 2026-09-20 (Phase 6.13e: a replay that replays)

**Branch:** `feature/loop-closes` · **Status:** 6.13e complete, gates green.

Replay counted findings whose titles happened to contain the rule's field name, said
nothing at all about a check or a compliance rule, and called the result "runs examined".
It is now a worker job (`replay`): each of the last `training.replay_runs` finalized runs
has its stored reports parsed again, with the same masking a run uses, and the drafted
rule is put through the pipeline's own evaluators — field constraints, named values with
the expression evaluator, configuration path presence. No model is called and nothing is
written to a run. The console shows *Replaying…* and polls until the result lands.

It is honest about its edges: firing means the rule would have raised a finding, not that
the finding would have been right, and the dismissal count is an estimate, because the
candidate has produced no findings of its own yet. Both are said on the card.

`validate_rule` now parses a drafted check with `expressions.validate`, so a malformed
expression is refused where it is written rather than becoming a run-time finding. The
golden-set claim has left the candidate model, the wire model and the setting's help.

**Found by replaying:** an approved field constraint lost its parameter. Synthesis answers
with `values`, `minimum`, `maximum` and `pattern`; approval read `body["value"]`, which is
not one of them, so every learned allowed-values, range and format constraint went live
unable to check anything. `synthesis.constraint_value` is now the one mapping between the
two shapes, used by approval and replay alike. A replay declining to fire on data that
plainly breaks the rule is what surfaced it.

**Next:** 6.13f, the remaining documents, then the phase closes.

---

## Session: 2026-09-20 (Phase 6.13d: worked examples an administrator can give the model)

**Branch:** `feature/loop-closes` · **Status:** 6.13d complete, gates green.

Every prompt's worked examples lived in Python. An administrator could teach the model
background prose, the validation guides and the meaning map, and not one *this wording
means this requirement* pair. `prompt_examples` (migration `e6f8a0b2c4d6`) holds theirs,
for six stages: extraction, description, tracing, judgment, classification and synthesis.

What makes it safe is what the screen shows. An example is a pair, never a sentence: what
the model would be shown and a good answer, with the answer validated against that
stage's own Pydantic schema on save, so an example the pipeline could not parse is
refused with the field named. The personal-data tripwire runs on save, because an example
is text pasted from a real delivery. The block is rendered after the built-in examples,
numbered on from them, under a line saying they show a shape and are not rules — and it
is inserted into the *rendered* prompt, so nothing an administrator wrote is ever read as
a placeholder, and the text being part of the prompt is what changes the cache key.

The cap is enforced where it is set: a stage carries four, and the console refuses a
fifth active one rather than storing a row that looks live and reaches nothing. Scope is
the one vocabulary; the narrowest are shown first. Versions per stage, with revert.

Promotion needs a click. The confirmed mapping keeps its button on the Meaning screen;
the other two sources have no screen an administrator looks at (the training console
lists drafts, and a requirement edit happens in the user app), so `GET /admin/corrections`
lists the requirements reviewers rewrote, and the Examples screen offers both those and
the rules approved from what reviewers wrote under *Teach from a correction somebody
already made*.

ADR-038 is written. 1213 Python tests, 86 admin-ui, 91 user-ui.

**Next:** 6.13e, a replay that replays.

---

## Session: 2026-09-20 (Phase 6.13c: judgment checks finished)

**Branch:** `feature/loop-closes` · **Status:** 6.13c complete, gates green.

A judgment check could be defined, stored and scoped, and stage 7 skipped it with a log
line. It now runs, under ADR-001: `CheckDefinitionRow.value_names` (migration
`d5e7f9a1b3c5`) names the values the model may see; the console's judgment form asks for
them and the API refuses a judgment check that names none. Stage 7 resolves only those
values, renders `name = value` lines and calls the registered `JUDGMENT_PROMPT` through
the adapter, cached and budgeted like every call. Code decides what the verdict becomes:
`fail` is a `judgment_failed` finding at the check's severity, `review` or a low-confidence
answer is a review item that says a person must judge, `pass` records nothing, an
unresolved value is `could_not_evaluate`, and a model that does not answer leaves a run
notice rather than a silent pass. A shadow judgment check produces a hidden finding.

Nine pipeline tests (`tests/pipeline/test_judgment.py`) and two API tests cover it. ADR-039
and ADR-040 are written, and ADR-021's item 6 is amended to say how the dismissal rate is
made — the code has cited all three since 6.13b. Acceptance criterion 7 is ticked.

**Next:** 6.13d, the controlled examples library.

---

## Session: 2026-09-20 (Phase 6.13b: the reviewer's loop closes)

**Branch:** `feature/loop-closes` · **Status:** 6.13b complete, gates green.

The author of an observation stopped hearing anything after "the model has drafted a
rule". Now *My observations* shows a chain — Waiting → Drafted → In shadow → Live, or
Switched off, or Not taken forward with the reason — and names the rule. The outcome is
**derived from the rule tables at read time** (`api/provenance.py`) rather than written at
approval, because a status written then would say "approved" forever while the rule went
live or was disabled.

A finding now says where it came from: `origin` is `built_in` when code produced it from
the OSL and the configuration alone, else the origin of the rule behind it, and a card
from a learned rule is marked *Learned from an observation*. *Rules applied to this run*
lists every rule that produced a visible finding and names the ones running silently.
Shadow findings are visible **to administrators only**, per rule on the Rules screen, with
a *Not a real problem* control that records a dismissal — which is what makes a shadow
rule's precision knowable before anyone activates it (ADR-040).

The button went where the opinion forms: the evidence drawer, every matrix row, every
coverage gap. The form asks for the sentence first and focuses it, the expectation second,
and the three settings sit under *Details*; anchors are chips that can be removed; Escape
and a click outside close it. Bulk OK says how many it marked and surfaces errors; the
run-page banner states the gate's own reason. `e2e/tests/train-ai.spec.ts` records from a
card, the drawer and a gap, and proves a second Save is an update.

---

## Session: 2026-09-20 (Phase 6.13a: the repairs)

**Branch:** `feature/loop-closes` · **Status:** 6.13a complete, gates green.

A second review traced the flow from upload to frozen report, the learning loop, and
every Train AI surface in the user app, in code, and found fifteen defects that no test
caught and no screen showed. `phase-6.13.md` lists them. Every one is fixed in this
milestone except D9 (judgment checks, its own milestone) and D11 (replay, its own), and
every fix carries a test that failed on `dev` first.

The two that mattered most: **the worker dropped the lens settings** — the console-aware
resolver built `LLMSettings` without them, so with the database reachable every
deployment ran on `single` whatever `.env` said — and **several files for one report kind
overwrote each other on disk**, so three labelled parts were three rows over one file.
The parts test passed because it uploaded identical bytes three times; it now uploads
distinct bytes and checks the files on disk.

The rest: a learned compliance rule wrote its own name as the path to look for; shadow
compliance rules never ran and their findings carried no rule reference; shadow
programme rules interrupted reviewers; the programme read saw `criteria: ()` instead of
the OSL sentence; AI context written on a report type reached no prompt; the console
could not approve a candidate that overlapped anything; pressing Save twice made two
observations; configuration notes appeared on My observations as "waiting"; a compliance
rule's expected value was never compared; every observation in a batch was linked to one
candidate. Two more came out while fixing: the redraft after a critique took the *first*
rule in the answer rather than the one about the same thing, and `last fired` on the
Rules screen was the last review.

The synthesis prompt is at version 2: statements are numbered and a rule says which it
came from; a compliance rule carries `json_path_contains`.

---

## Session: 2026-09-20 (Phase 6.12: one scope vocabulary and one front door)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1135 Python
tests, 91 user-ui, 84 admin-ui.

Two things, and deliberately not a third. The phase document says what was left out and
why: the overlapping surfaces are not merged and the sixteen screens are not rewritten,
because each merge is a migration and a behaviour change, and doing them behind a front
door that already hides the difference would be paying the risk for something nobody
sees.

### One module reads a scope (ADR-037)

Four shapes had been stored over the product's life — `all`, a bare customer name,
`programme:CODE` and `config:ID` — and each reader recognised some of them. `scopes.py`
is now the only thing that interprets one: `parse` takes every form, `token` renders the
canonical one, `covers` answers the question, `label` is for a screen. The stored columns
are untouched; a row becomes canonical the next time somebody saves it, and one pydantic
type canonicalises the wire in both directions so no router has to remember.

**This found a real bug.** A field constraint scoped to a delivery programme never ran:
the loader compared the stored string against `all`, the customer name and `config:ID`
and nothing else, so the rule was loaded on every run and matched on none. It was
invisible, because a rule that never fires looks exactly like a rule with nothing to say.
`load_admin_config` now takes the run's programme and asks `scopes.covers`.

`all` became `everywhere` because `all` was already taken: the rule schema's
`applies_to: "all"` means every **record**, not every **run**, and one of them is in the
model's output schema.

### The front door

One box, `POST /admin/front-door`, and a **Tell the tool** screen at the top of the admin
sidebar. One new prompt, `admin_classify`, answers which of the existing surfaces a
sentence belongs on, from a closed set. Everything after that is `training.synthesis`
unchanged: the drafting, the validation, the fingerprint, the conflict check, the
critique pass and the approval. There is no new rule table, no new evaluator and no new
branch in the approval path, which is the whole point — a front door that added a surface
would make seventeen.

Two answers create nothing. **Background** ("the second tab is the reissue file") is said
to be background and offered to the screen that holds background, rather than forced into
a rule that would then be wrong. **Unclear** comes back with the model's question and
writes no candidate and no observation.

The classification routes; it does not draft. Passing the chosen surface into the
synthesis prompt would have meant changing that prompt, bumping its version and
discarding its cache, to tell it something it works out anyway. When the two readings
disagree, the answer says so instead of hiding it.

### A bug in the browser harness, found on the way

The browser suite was failing intermittently, and the first job was to establish that it
was not this work: it fails the same way on the previous commit, two runs in three. The
cause is that **Playwright starts the web servers before it runs global setup**, and
global setup was what wiped and seeded the database. The API therefore opened the
previous run's file and kept it after the wipe — SQLite keeps a deleted file open — so
the whole suite read and wrote a database nothing else could see.

It presented as caching and was nothing of the kind: a run already frozen before any
test touched it, and review decisions that returned 200 and were nowhere afterwards.
Seeding now happens inside the API's own web-server command, which is the only ordering
that guarantees one database. Two further fixes came out of the same investigation: the
decide loop drives from the server's list of undecided findings rather than from the
cards, and an assertion after a reload waits for the element rather than for the
navigation. Thirty browser tests, green twice in a row.

### Tests

14 on the front door, 30 on the scope module, 3 more in the admin console. The three
statements the phase document names as acceptance criteria are asserted verbatim, and the
scripted stand-in gained a classifier plus three rule shapes so those assertions mean
something. The stand-in refuses anything it does not recognise, so "asks a question
rather than guessing" cannot pass for the wrong reason.

---

## Session: 2026-09-20 (four eyes on what one reviewer waved through)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1084 Python
tests, 91 user-ui, 81 admin-ui.

A delivery programme can now require that someone other than the reviewer signs off a
run whose serious findings the reviewer marked OK: a breach of a rule the programme
calls `must`, or a compliance rule the configuration does not implement. ADR-036 has
the shape. Off by default, because programmes differ in what a waved-through compliance
finding costs.

It is deliberately narrow. **A signature, not a re-review**: the second person is shown
what was waved through and says the run can be frozen, and nothing claims they redid the
work. **From someone else**: an approval from the reviewer who made those decisions is
refused. Deciding a serious finding Not OK needs no second signature — the trigger is
waving it through, not seriousness.

### The thing worth remembering

**With login off the rule stands down entirely.** Everyone is then the same placeholder
account, so a "second" approver is the same person and every affected run would be
unfinalizable forever. A gate nobody can pass is worse than no gate: it teaches people
to look for a way round, and the way round is switching the whole thing off. The first
test written failed for exactly this reason, which is how the trap was found. The admin
console says it beside the switch and the deployment checklist says it beside login.

A second thing came out of that: the gate was reading auth settings from the
environment rather than the ones the app was built with, so an app running with login
on was told it was off. The settings are passed in now.

### Next concrete action

Phase 6.12: one front door for the admin console — say it in words, the model routes the
statement onto the right existing rule surface and drafts it, an administrator confirms
it into shadow — and one scope vocabulary in place of today's three.

---

## Session: 2026-09-20 (Explore a sample: the last 6.1 item)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1076 Python
tests, 91 user-ui, 81 admin-ui, 26 browser.

A reviewer could only anchor an observation to a finding, so they could only tell the
tool about what it had already noticed. What a person knows is usually about what it
said nothing about. **Explore a sample** (`user-ui/app/explore`) serves the stored
samples read-only: a workbook cell by cell with its label, an OSL by section, a
configuration by JSON path, each of them something to point at. With Train AI mode on
every one carries a "What should this check?" button. It is the admin console's preview
reused, with the same masking: two renderings of one workbook that could disagree would
be worse than one.

### Found on the way, in the browser suite

Two flakes that were both real, and both now written down in `e2e/README.md`:

- **`reuseExistingServer` was carrying state between runs.** Global setup wipes the
  database, so a server left from an earlier run is attached to the one it wiped. It is
  false everywhere now.
- **The finding list renders progressively.** A count taken from the screen missed a
  finding, which left the gate shut for a reason the test could not see. The test asks
  the API how many findings there are, waits for that many cards, and asserts the run
  ends frozen rather than the status of one reply — a second identical finalize is
  refused by design (ADR-005), which is not a failure.

### Next concrete action

Four-eyes: a programme-level switch requiring a second approver before finalize when a
`must` programme breach or a compliance finding was marked OK. Off by default, and
meaningful only with login on. Then Phase 6.12.

---

## Session: 2026-09-20 (closing the open items in 6.1, 6.2 and 6.4)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1071 Python
tests, 91 user-ui, 81 admin-ui, 26 browser.

Four items that had sat unticked in closed phases.

**The frozen report names its submitter and its reviewers (6.2d).** Reviewers come from
the decisions themselves, so a run nobody decided names nobody rather than implying a
review that did not happen. With login off both are the seeded placeholder, which is
attribution and not authentication — a distinction the deployment checklist now makes
explicitly.

**A contradiction is flagged when the observation is written, not weeks later
(6.1e).** `training/conflicts.py` finds the active rules covering the same field or
anchor and marks one the statement reverses. It comes back with the saved observation
and the dialog shows it. Nothing is blocked: an observation contradicting an active
rule is often the signal that the old rule is wrong (ADR-021). Detection at the
candidate stage is unchanged; this is the second moment, where the author still
remembers writing the sentence.

**The deployment checklist gained a "Login and attribution" section (6.2f):** both
switches, the bootstrap password the API refuses to serve past, two administrators
rather than one, TLS so the cookie is `Secure`, and a spot-check of the audit log. A
half-configured sign-in looks like protection and is not.

**The Train AI indicator is covered rendered, in both states (6.4).** The suites
covered the client that reads the switch and never the thing a person looks at.

### Next concrete action

Four-eyes: a programme-level switch requiring a second approver before finalize when a
`must` programme breach or a compliance finding was marked OK. Off by default, and
meaningful only with login on. Then Phase 6.12.

---

## Session: 2026-09-20 (browser tests in CI)

**Branch:** `feature/nothing-slips` · **Status:** complete — 26 browser tests green,
twice in a row, plus every existing gate.

`e2e/` holds Playwright tests over both apps against a real API, a real worker and a
throwaway database seeded by `scripts/seed_demo.py`. Playwright starts the API and both
apps; the worker has no URL to poll, so global setup starts it and teardown stops it.
The scripted stand-in answers every model call, so the suite needs no network. A new
`browser` job runs it in the manual-dispatch workflow and uploads the report on failure.

Covered: the runs list in every lifecycle state, the matrix and coverage panel, the
three decisions, Not OK refused on a high finding without a comment, the evidence
drawer, the frozen report, drift; the whole finalize gate end to end; every admin
screen loading without a page error, the typed-word confirmation, a setting's layer;
the four palettes and two screens at phone width.

### Found on the way

**A real defect, fixed.** The coverage panel returned `null` when its request failed,
so a reviewer would see no panel and no explanation — the panel whose entire purpose is
to say that the absence of a finding is not a pass would have vanished silently. It now
shows the error and offers to retry. The browser suite found it because the panel
disappeared under a request raced by a navigation.

**Three test-quality lessons**, written into `e2e/README.md` so the next suite starts
there: assert outcomes rather than transient text (a finding card carries
`data-review-status`, so a decision is confirmed by state and not by a message that
clears); do not count elements before a list has loaded, and do not hold a locator that
re-resolves as state changes; and the screens read their run when they mount, so a test
that changes state reloads rather than asserting a live update the app never promised.

### Next concrete action

The small items left open in closed phases: the frozen report naming its submitter and
reviewer (6.2), the standalone sample-exploration screen and anchoring by OSL section or
configuration path (6.1), flagging a contradicting observation when it is written
(6.1), the open configuration-note test (6.4), and the deployment production checklist
(6.2).

---

## Session: 2026-09-20 (Phase 6.11b: the benchmark harness — 6.11 complete)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1066 Python
tests, 88 user-ui, 81 admin-ui.

`scripts/golden_set.py` now reports **coverage and model calls** beside precision and
recall, **per programme** as well as per finding type, and takes a **`--lenses` switch**
so a change to stage 8 is compared rather than argued. A case whose coverage drifts from
its oracle fails even when its findings are right: a run that finds nothing because it
compared nothing used to score perfectly.

**Three new golden cases**, not the two the phase doc planned:

- `unevidenced_requirement` — an `other` clause the configuration implements and no
  report check can reach. Its findings list is empty and its coverage is not, which is
  the whole point of Phase 6.11.
- `report_nothing_checks` — a report type nothing examines.
- `credit_date_not_in_reports` — **the first case in the set to produce a low-severity
  finding.** Nothing had, which is why the bulk-OK defect fixed in 6.11a went untested.

**The lens comparison, and what it settled.** Both variants score identically on the
synthetic set: 15/15, 100% precision and recall, the same coverage, 323 calls against
345. That is not evidence the lenses are pointless — the scripted stand-in returns the
same canned agreement to every lens, so the comparison measures the fixtures, which is
ADR-028's lesson over again. It does establish that the three cost about 7% more rather
than three times more, and that turning them on changes no finding when the readers
agree. **`LLM_VERIFY_LENSES` stays at `single`**; the comparison that decides it runs on
the target environment. Written up in `docs/benchmarks/README.md`.

### Found on the way

The stand-in needed teaching to read free-text OSL clauses as `other` requirements and
to describe a policy configuration block as one, or the new case could not exist. Two
clauses in one case both linked to the same configuration element, leaving the other
orphaned as a spurious finding; one clause makes the case say what it means.

### Next concrete action

**Browser tests in CI** on this branch: Playwright over both apps against the seeded
stack with the scripted model, wired into the manual-dispatch workflow. Cover submit,
review and finalize, the coverage panel and acknowledge, the PDF, login on, the training
queue, a setting change, a rule action with the typed word, Map on Meaning, the
palettes, a narrow viewport.

---

## Session: 2026-09-20 (Phase 6.11c–h: coverage, the gate, the lenses)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 1058 Python
tests, 88 user-ui tests, `black`/`flake8`/`mypy`/lint/typecheck/format/build clean.

Built in the order the user asked for: c through h, with b (the benchmark harness)
deferred.

**Coverage (6.11c).** Stage 7 records what it evaluated as it goes; `pipeline/coverage`
turns that into one state per requirement — checked, traced but unchecked, untraced,
verified by hand — with the reason, plus how many checks touched each uploaded report.
Pure code. Stored on the run, served at `GET /runs/{id}/coverage`, a panel on the
review screen and a "What was checked" section in the frozen report. The summary prompt
is given the counts (version 2) so it cannot call a delivery clean when part of it was
never examined. Drift gains what a report evidenced last time and does not now. A
verification or programme reading that could not run is a notice the reviewer sees.

**The gate fails closed (6.11d, ADR-035).** Every high **and** every `review` finding
decided, every unevidenced requirement and unevaluated check acknowledged. One
implementation in `api/gate.py` answers both the screen and finalize, refused with 409.
Finalizing shows the attestation and stores it on the report.

**Three lenses (6.11e, ADR-034).** Delivery, compliance, requirements owner, each given
the same finding and evidence and none given another's answer; code merges. Any
disagreement sends the finding to a person with every reason. A lens may raise a
question from the same evidence, which becomes a review item, deduplicated across
findings; it can never raise a severity. A lens that fails counts as neither, so two
that agree still verify. `LLM_VERIFY_LENSES` **stays at `single`** — today's behaviour,
call for call — until 6.11b measures the three. Also: stage 4 now receives the
preamble, and the whole guidance block has a ceiling (it was capped per field, so ten
configuration notes were ten times the cap).

**The coverage reader (6.11f)** asks which unevidenced requirements read like
obligations; an invented requirement id is dropped. **The critique pass (6.11g)** reads
a drafted rule back against the statements with one redraft, keeping both versions, and
approving a candidate that overlaps an existing rule now requires supersede or
keep-both.

**Docs:** ADR-034, ADR-035, design, architecture, privacy, glossary, both training
documents, the rollout readiness list.

### Found on the way

- **No synthetic fixture leaves a requirement unevidenced**, so the coverage-reader
  tests build the state directly rather than skipping. 6.11b adds the golden case.
- **The same lens proposal arrives once per finding.** Deduplicated within a run, with
  every lens that raised it named.

### Next concrete action

**6.11b, the benchmark harness**: expected findings in the golden fixtures, precision
and recall per finding type and per programme out of `scripts/golden_set.py` into
`docs/benchmarks/`, the `LLM_PIPELINE_VARIANT` switch, and the new cases (a requirement
no report can evidence; a custom report with no checks; one that yields a low-severity
finding). Then the measurement that decides whether `LLM_VERIFY_LENSES` moves off
`single`. Browser tests in CI follow.

---

## Session: 2026-09-20 (Phase 6.11a: review defects and decision quality)

**Branch:** `feature/nothing-slips` · **Status:** complete, gates green — 966 Python
tests, 88 user-ui tests, `black`/`flake8`/`mypy`/lint/typecheck/format/build clean.

- **The bulk-OK defect is fixed.** `bulk_ok_low_severity` writes `false_positive`; it
  wrote `confirmed`, which reads as Not OK on the screen and turns the run's verdict,
  so one click on "Mark all low OK" failed a clean delivery.
- **Three decisions on the review screen**, not two: False positive, Accepted risk,
  Not OK. Every OK used to be stored as `false_positive` and `accepted_risk` was
  unreachable from the UI although the schema had it all along.
- **A decision has to say what it means.** `decision_problem` (findings router)
  refuses with 422 a Not OK on a high or review finding with no comment, and an
  accepted risk with no comment at any severity. `decisionProblem`
  (`user-ui/lib/display.ts`) is the same rule client-side, so the reviewer is asked
  before the request rather than losing what they typed.
- **Finalize asks once**, through `confirm-dialog`, showing the finding counts and
  what freezing means. The attestation block replaces that body in 6.11d.

**Two things found while doing it**, both recorded in `phase-6.11.md` "Found on the way":

1. **No fixture case produces a low-severity finding**, so the existing bulk-OK test
   had always passed on zero rows and proved nothing. The tests now create one
   (`_add_low_finding`).
2. **Every fixture case, the clean baseline included, carries two `could_not_evaluate`
   findings at `review` severity**, and the gate lets them through undecided. That is
   the hole 6.11c and 6.11d close, now confirmed on real output.

A drift test helper that marked high findings Not OK with no comment started failing,
correctly, and was given one.

### Next concrete action

**6.11b, the benchmark harness**, on the same branch: expected findings in the golden
fixtures, precision and recall per finding type and per programme out of
`scripts/golden_set.py` into `docs/benchmarks/`, the `LLM_PIPELINE_VARIANT` switch, and
the two new cases (a requirement no report can evidence; a custom report type with no
checks — and one that yields a low-severity finding, per the note above).

---

## Session: 2026-09-20 (product review → Phase 6.11 specified)

**Branch:** session branch, docs only · **Status:** `docs/phase-6.11.md` written and
indexed; no code changed.

A review of the product as built, asked for before the next work: ease of use, human
error, whether a compliance error can slip, and whether a multi-agent "personas
debate" loop would help. Verified in code:

- **Defect:** `POST /runs/{id}/findings/bulk-ok` writes `confirmed`, the Not OK value
  in `display.ts` and `render.py`. "Mark all low OK" flips a clean run's verdict to
  `not_ok`. The test asserts only "not undecided". Fix is 6.11a's first item.
- Every OK from the screen is stored as `false_positive`; `accepted_risk` is
  unreachable. No comment is ever required. Finalize has no confirm.
- The gate covers high findings only; `review`-severity findings can be left
  undecided through finalize. No coverage concept: a requirement traced but never
  checked in any report, and a custom report with zero checks, are silent.
- Stage 4 gets the guide block but not the preamble; the preamble clip is per field.
- Synthesis detects conflicts but approval of a conflicting candidate is not blocked.
- Sixteen admin surfaces, three scope vocabularies; overlap among guides, meaning
  entries and named values, and among programme rules, compliance rules and judgment
  checks. Named as Phase 6.12, not yet specified.
- No benchmark harness with precision and recall, which the rollout plan's gates need.

**Decisions** (user): no debate loop; three independent lenses (Delivery, Compliance,
Requirements owner) at stage 8 merged by code, confidence only, never a severity up;
a fail-closed finalize gate with an attestation; four-eyes deferred; the admin front
door is Phase 6.12; 6.11 runs before browser tests, with the benchmark harness inside
it. Full reasoning in `docs/phase-6.11.md` "The idea".

### Next concrete action

Cut `feature/nothing-slips` from `dev`. 6.11a first: the bulk-OK fix with the
finalize-after-bulk-OK test, then reason codes and required comments, then the confirm
on finalize. Then 6.11b, the harness, before any coverage or lens work. *(6.11a landed
the same day; see the session above.)*

---

## Session: 2026-09-20 (hand-off)

`dev` and `main` are identical and every feature branch is merged. The next task, in
the agreed order, is **browser tests in CI**: Playwright end-to-end tests over both
apps against the seeded stack with the scripted model (`LLM_PROVIDER=mock`,
`scripts/seed_demo.py`), wired into the manual-dispatch CI workflow. Cover: submit a
run with parts and delivery context, review and finalize, download the PDF, sign in
when login is on, work the training queue, change a setting, act on a rule with the
typed word, Map on the Meaning screen (mock), the four palettes, a narrow viewport.
Branch `feature/browser-tests` from `main`; PR to `dev`; promote.

Skipped for now by decision: ownership/notifications. **Target PC only:** Phase 7,
the real benchmark on the in-house gateway, `docker compose` verification, the
Postgres load test, Meaning on the real samples.

---

## Session: 2026-09-20 (samples grouped by scope, with notes)

Artifact types: samples in one box per scope (Global, then each programme) with
its own add form; label, notes and programme editable on a sample; notes on the OSL
and configuration samples reach the mapping interview.

---

## Session: 2026-09-20 (documents brought current)

Architecture (the `meaning/` package, the API row), CLAUDE.md's package list, the
training documents' alignment date, the presentation brief (admin table, status),
and the rollout readiness list, all describing the code at this commit.

---

## Session: 2026-09-20 (Phase 6.10 Part B: Meaning)

**Branch:** `feature/meaning` · **Status:** complete, gates green.

- Samples scoped per programme; `meaning_entries`; the mapping interview
  (`admin_map_requirement`, one cached call per OSL section); confirm → shadow check
  and shadow compliance rule; global + programme entries reach stages 4 and 8; the
  Meaning screen with By requirement / By report cell tabs and versions. ADR-033.

### Next concrete action

Browser tests for the core flows, in CI (last item of the agreed order).

---

## Session: 2026-09-19 (Phase 6.10 Part A: edit and typed delete everywhere)

**Branch:** `feature/edit-and-confirm` · **Status:** complete, gates green.

- Every admin delete requires the typed word, API-enforced; bulk delete on the long
  lists and a bulk state action on the Rules screen; compliance rules editable with
  a version; checks editable from the list; Rules screen links to the owning screen.
- Delivery programme cards tinted and bordered; user tab title "Greenlight AI".
- ADR-032; `docs/phase-6.10.md` written with the decisions for Part B (Meaning).

### Also this session

- Configuration id required again, never unique; credit date and run date shown
  beside it on the run list and the run page (`feature/config-id-required`).
- **First real runs on Haiku** through the demo stack: four fixture cases submitted,
  all reached review with the expected findings (score 755 vs 750, the missing
  waterfall step, states outside the set); one finalized with the frozen report and
  PDF. The seeded programme rules fire on the synthetic fixtures (no opt-out text
  there), which is the rules working, not a defect. Benchmark and the real admin
  definitions come later, on the target PC.

### Next concrete action

Part B on `feature/meaning`: scoped samples + `meaning_entries` + migration first.

---

## Session: 2026-09-19 (artifact types: three tabs, PDF OSLs, version labels)

**Branch:** `feature/artifacts-tabs` · **Status:** complete, gates green.

- Artifact types screen: tabs for Requirements (OSL), Solution Canvas (ETL
  configuration) and Reports; named values and guides under Reports; each type and
  programme shows its definition version as `v1.n`.
- Samples preview by kind: an OSL by section and paragraph, a configuration by block
  and path. Before this, an OSL sample was pushed through the workbook parser and
  failed.
- OSLs may be PDF: `parsers/osl_pdf.py` (pypdf) behind the same Protocol, chosen by
  suffix; accepted on the new-run form and as a sample.

---

## Session: 2026-09-19 (Phase 6.6: the theme picker)

**Branch:** `feature/theme-picker` · **Status:** complete; 934 Python tests, 82 user-ui,
77 admin-ui, gates green; browser check of stepping, reload, and lock passed.

### What was completed

- `ui.theme` and `ui.theme_locked` in the Appearance settings group; the public
  `GET /appearance`; both apps read it per request and re-read it in open tabs.
- A theme picker at the foot of both sidebars, hidden when locked; the choice kept
  per browser. A contrast test per app over every palette in both modes. ADR-031.

### Next concrete action

Browser tests for the core flows, in CI (the last item of the agreed order).

---

## Session: 2026-09-19 (Phase 6.9: delivery drift)

**Branch:** `feature/delivery-drift` · **Status:** complete, 932 tests, gates green.

### What was completed

- `db/drift.py`, `GET /runs/{id}/drift`, the review-screen card, and the frozen
  report section: new, resolved and carried-over Not OK findings, requirements whose
  value changed, and the configuration diff by path, all against the previous
  finalized run of the same configuration. ADR-030; the design-doc question ticked.

### Next concrete action

Phase 6.6, the theme picker; then browser tests.

---

## Session: 2026-09-19 (Phase 6.8: scoped compliance, versions, validation guides)

**Branch:** `feature/validation-guides` · **Status:** complete, 924 tests, gates green.

### What was completed

- **6.8a** Checks and compliance rules scoped to a programme (`programme:CODE`);
  scope picker on both screens.
- **6.8c** Ten versions of every artifact type (fields, samples, guide) and every
  programme's rule set; revert with the typed word; runs record the versions they
  were processed under; the sweep prunes beyond ten but keeps what a live run names.
  Fixed on the way: samples of one type shared one path on disk and overwrote.
- **6.8b** Validation guides: a guide editor per report type, examples filled from
  the samples, entries read by stages 4 and 8 as background, concrete entries
  compiled into shadow checks with origin `guide`; config-path named values.
- Two ADR-021 gaps closed: shadow checks never ran; shadow findings were visible to
  reviewers, counted, gated finalization, and reached the report and the summary.
- ADR-029. Migrations `d7a1c2e4f6b8`, `e8b2d4f6a1c3`.

### Build order agreed with the user

Delivery drift → Phase 6.6 theme picker → browser tests. Skipped for now:
ownership/notifications. **On the target PC only:** Phase 7, the real benchmark
against the in-house gateway, `docker compose` verification, the Postgres load test.

### Next concrete action

Open the PR for `feature/validation-guides` against `dev`; then delivery drift.

---

## Session: 2026-09-19 (credit date; first real model)

**Branch:** `feature/credit-date` · **Status:** complete, 895 tests, gates green.

### What was completed

- Runs get their own identity; the configuration id is information and may repeat;
  the run date becomes the **credit date**, and code checks the artifacts carry it
  (`credit_date_missing`). Deliverable-count fields removed from the form. Every
  form and console field says whether the model sees it. ADR-027, migration
  `b614b77ca9d8`.
- The golden set ran against a real model for the first time: **0 / 12**, every case
  rejected at stage 2 for extra keys. Stages 2 and 3 now fold the answer onto the
  schema before validating; prompts name the exact keys and read exclusions, steps,
  counts and the input population the same way on both sides. Result **12 / 12**,
  recorded in `docs/benchmarks/phase-2-real-model.md`. ADR-028.
- **Benchmarking stops here** (user decision): no larger-model comparison on
  synthetic fixtures. The real benchmark is a to-do for the target environment, with
  real OSLs and reports and the in-house gateway; it opens Phase 7.

### To-do, target environment

- Run `scripts/golden_set.py` against the in-house gateway on real files, record
  `docs/benchmarks/phase-2.md`, bump prompt versions as the fixes demand. Closes
  Phase 2 criterion 2 and Phase 6 criterion 2.
- Rotate the hosted API key that was used for the first run.

### Next concrete action

Merge PR 9 and this branch into `dev`, promote to `main`; then item 4 of the
top-five plan: browser tests for the core flows, in CI.

---

## Session: 2026-09-19 (programme rules and the programme check)

**Branch:** `feature/programme-rules` · **Status:** backend complete, 886 tests;
admin screen in progress.

### What was completed

- Programme rules: several per programme, each with a strictness (must, should,
  advisory). Stage 8 has the model read the delivery against them and name breaches
  with evidence; code sets the severity from the strictness and discards any rule id
  the model invents. A fourth rule kind on the Rules screen, with the full lifecycle.
- The programme check: admin-editable keywords per programme, seeded; stage 7 greps
  the OSL, configuration, and report headers, and a run declared as one programme
  that reads like another gets a high finding naming both.
- ADR-026, Phase 6.7, migration `64aeccf26047` verified up and down.

### Next concrete action

Merge the admin screen, open the pull request against `dev`.

---

## Session: 2026-09-19 (the logo)

**Branch:** `feature/logo` · **Status:** complete, gates green.

### What was completed

- The Greenlight AI mark, a traffic signal with the green lit, as one `Logo`
  component per app with a size and a glow prop, in the sidebar brand block (which
  now links home), on both sign-in screens, as the favicon, on the frozen report,
  and in the mock. The admin console carries a small "Admin" label after the name.
- The brand box behind the mark is the brand yellow in every theme, the one
  surface in the rail that does not follow the palette, so the dark housing reads on
  the navy default.
- Carried in the wording commit that missed pull request 6 by two minutes.

### Next concrete action

Open the pull request "Add Greenlight AI logo to user-ui and admin-ui headers".

---

## Session: 2026-09-19 (renamed to Greenlight AI)

**Branch:** `chore/rename-greenlight-ai` · **Status:** complete, gates green.

### What was completed

- The product is **Greenlight AI** everywhere (ADR-025): the Python package
  `greenlight_ai`, the distribution and console script `greenlight-ai`, every
  `GREENLIGHT_AI_*` setting, the compose project and Postgres defaults, both apps,
  the mock, the frozen report, and every document. Eight commits, one per area.
- The mark is a green light in the brand box; the tagline sits under the wordmark
  in both sidebars, on the sign-in screens, in the mock, and on the report.
- 871 Python tests, 63 user-ui, 50 admin-ui; every migration loads on a fresh
  database; compose validated as YAML because Docker is not installed here.

### Pending

- The user renames the GitHub repository and the remote, then the two documentation
  URLs. A local `.env` or shell exports under the old prefix need the new names.

### Next concrete action

Open the pull request "Rename vigilAI to Greenlight AI" against `dev`.

---

## Session: 2026-09-19 (phase 6.4 built; branch rule)

**Branch:** `feature/train-ai-visibility` · **Status:** complete, gates green.
871 Python tests, 48 admin-ui, 61 user-ui.

### What was completed

- Pull request 1 merged into `main` and `dev` created from it. The merge had not
  landed when the user thought it had; done from here on their word.
- **Branch rule**: a branch is named for the work, never for who typed it. The
  working branch was renamed from `claude/…` to `feature/train-ai-visibility` and the
  rule is now explicit in `standards/git.md` and `CLAUDE.md`.
- **Phase 6.4**: a Train AI indicator under the mark in both apps, green when on and
  grey when off, with every mode-only control tagged. Configuration notes (ADR-024):
  an observation of kind `config_note` tied to the ETL configuration id, background
  for every future run of it, a comment in the admin queue, and synthesizable into a
  rule scoped `config:<id>`. Available whatever the mode. The run page and the frozen
  report show the notes the model was given.
- The demo seed fills the training queue and adds a configuration note, because the
  mock model returns empty shapes and a live synthesize would otherwise show nothing.

### Pending

- A rendered test that the indicator shows both states.
- Items left open in 6.1 and 6.2, and everything under "Outstanding, needs the user".

### Next concrete action

Open a pull request from `feature/train-ai-visibility` to `dev`.

---

## Session: 2026-09-18 (phases 6.1, 6.2 and 6.3 built)

**Branch:** `claude/funny-cerf-jsyvpe` · **Status:** complete, gates green.
862 Python tests, 45 admin-ui tests, 55 user-ui tests; `black`, `flake8`, `mypy`,
`check_docs`, and both UIs' five gates all clean.

### What was completed

- **Phase 6.2**: `auth/` with scrypt passwords and server-side sessions, the bootstrap
  administrator, account administration, attribution on runs, reviews, captured
  configs and audit entries, and login pages in both apps.
- **Phase 6.3**: `config/` with a registry, three-layer resolution, an encrypted
  secret, a change log, and the settings screen showing each value's source.
- **Phase 6.1**: `artifact_samples`, report parts, delivery counts, workbook
  detection, `training/` with the rule lifecycle and synthesis, field constraints,
  and the training and rules screens.
- Five migrations, each verified up and down, two of them moving data first.

### Four defects the work itself surfaced

- Every **read-only admin route was unguarded**: only the mutating ones called the old
  admin helper. The router now depends on `require_admin` as a whole.
- A **failed sign-in was rolled back with its own request**, so the lockout counter
  never survived its increment. It commits before raising.
- **Synthesis marked observations even when it produced nothing**, stranding their
  authors. Found by running it live, not by a test.
- **Three settings were unreachable**: black had already reformatted the `GROUPS`
  tuple, so the edit adding the section silently missed, and the endpoint renders
  group by group. A test now asserts every setting belongs to a listed group.

### Pending

- Phase 6.1: the standalone sample-exploration screen, and flagging a contradiction
  when an observation is written rather than at the candidate stage.
- Phase 6.2: naming the reviewer of each decision on the frozen report.
- Everything under "Outstanding, needs the user".

### Blockers

None.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (rule lifecycle settled; no rule expires on its own)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.1 (specification) ·
**Status:** decided, nothing built.

### What was completed

- The last open design question answered. Learned rules **never expire on their own**,
  because nothing inside the system can tell a load-bearing rule from a dead one.
- New milestone 6.1i, one searchable **Rules** screen holding checks, compliance
  rules, and field constraints together with an origin column, a state filter
  defaulting to active, and per-rule statistics.
- The lifecycle gained `disabled` (reversible) and a **soft delete restorable for six
  months**, then permanent with a tombstone so findings on old runs that cite a rule
  still explain themselves. `retired` is gone; it was a second word for `disabled`.
- Enable, disable, delete, and restore each require the administrator to type the
  word. Noted in the doc that typing to confirm on the two reversible actions is
  deliberate and is the thing to reconsider if it becomes friction.
- ADR-021 gained decision 11 and a consequence: because nothing expires, the rule set
  grows unless someone tends it, which is what the noisy-rule and dead-rule reports
  are for.

### Pending

Both phases are fully specified and decided. Nothing is built.

### Blockers

None.

### Next concrete action

See "Resume here": Phase 6.2, milestone 6.2a.

---

## Session: 2026-09-18 (design questions answered; ADR-021 and ADR-022 accepted)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.1 and 6.2 (specification) ·
**Status:** decided, nothing built.

### What was completed

- Sixteen open design questions put to the user and answered. Each phase doc now
  carries a **Decisions** table in place of its open-questions list, and both ADRs
  moved from proposed to accepted.
- Two answers went against the recommendation and are recorded as chosen, not as
  suggested: **an administrator activates a shadowed rule by judgement** with the
  numbers shown, rather than passing a fixed sample-and-precision bar, because a
  rarely-firing rule would otherwise wait forever for a sample it never gets. And
  single sign-on is **expected**, so the session table is shaped to accept an external
  provider.
- Build order set by the user: **6.2 first, then 6.1.**

### Pending

- Everything in both phases; they are specified and decided but unbuilt.
- One open question: does a learned rule ever expire?

### Blockers

None. Phase 6.2 can start.

### Next concrete action

Build Phase 6.2 milestone 6.2a: give `current_user()` a real body, seed the
placeholder account, and add the `admin_required` dependency, with both switches
defaulting to off so the existing suite passes unchanged.

---

## Session: 2026-09-18 (Phase 6.2 specified — optional login and attribution)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.2 (specification only) ·
**Status:** documented, nothing built.

### What was completed

- `docs/phase-6.2.md`: six milestones. One identity whether or not login is on;
  accounts an administrator creates with a forced first-sign-in password change;
  server-side sessions with revocation; attribution on runs, reviews, config history,
  and the frozen report; the append-only training record; docs and tests.
- ADR-022 (**proposed**), amending ADR-008: login exists, ships off behind two
  independent switches, and there is always a current user.
- The seam ADR-008 left turns out to be sufficient. `api/deps.py` already defines
  `CurrentUser` and `current_user()`, and every router already depends on it, so the
  API change is one function body plus a session table and actor columns.
- The user's record-keeping rule is written down explicitly: synthesis **marks** an
  observation as synthesized with its date and target and never consumes or deletes
  it, and re-synthesis produces a new candidate rather than editing the old one.

### Pending

- The five open questions at the foot of the phase doc, chiefly whether production
  should refuse to start while the bootstrap password stands.
- Phase 6.1's six open questions, still unanswered.

### Blockers

None.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 6.1 specified — richer inputs and a trainable rule loop)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6.1 (specification only) ·
**Status:** documented, nothing built.

### What was completed

- `docs/phase-6.1.md`: eight milestones covering up to three samples per artifact type
  with view and download, several files per report type with per-part findings,
  delivery counts that code verifies, workbook type detection that is deterministic
  first and asks when unsure, and the training loop.
- ADR-021 (**proposed**): observations are anchored to a cell, clause, or config path
  rather than being prose alone; suggested and active are different states; the model
  emits a schema-constrained rule object and has no authority to write or activate;
  candidates are replayed against the golden set and recent runs before approval; an
  approved rule runs in shadow until its dismissal rate earns activation; provenance
  includes the diff between the model's draft and the approved rule.
- Prior art surveyed and recorded in the phase doc: Great Expectations, Soda, Deequ
  constraint suggestion, dbt, and the suggested-monitor products. They agree on the
  point that matters — machine-suggested rules never auto-promote.
- `scripts/update_phase_status.py` now globs `phase-[0-6]*.md`, so 6.1's markers are
  derived and checked like every other phase. Glossary, phase-plan, CLAUDE.md, and
  README updated.

### Pending

- The six open questions at the foot of the phase doc. Each becomes an ADR, and
  ADR-021 cannot move from proposed to accepted until they are answered.

### Blockers

Nothing technical. The design is decided enough to build once those answers land.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (admin-configurable artifact types and run scope — ADR-020)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** amendment to Phase 4 · **Status:**
complete, all gates green.

### What was completed

- **The catalog left the code.** `ReportKind` is an open string with the built-ins
  listed; an unknown key is read by `GenericReportParser`. `artifact_types` replaces
  `report_templates` and covers the OSL and the config as well as each report, each
  with a label, a description, a sample workbook, an `ai_context` field, and active and
  required switches. `run_scopes` holds AM, AS, Archives, and a catch-all with standing
  instructions; a run records its scope and a suppressions answer defaulting to no.
- **Guidance is additive.** `pipeline/guidance.py` builds a preamble that labels itself
  background rather than requirement, and returns an empty string when nothing is
  configured, so a fresh install sends the prompts it always sent. The preamble is part
  of the rendered prompt, so editing guidance invalidates exactly the affected cache
  entries and nothing else.
- **The new-run form is generated** from `GET /runs/options`: dynamic upload slots, a
  programme dropdown, and a suppressions radio defaulting to No. admin-ui gained the
  **Artifact types** and **Delivery programmes** screens, and `/templates` is gone.
- **The user-ui sidebar gained an Admin console launcher**, at the user's request.
- Migration `7055ed7523c8`, 26 new tests, ADR-020, and the design, architecture,
  phase-4, phase-7, and README updates.

### The bug worth remembering

`fastapi.UploadFile` is a **subclass** of `starlette.datastructures.UploadFile`, and
`request.form()` yields the Starlette one. Reading the report uploads dynamically meant
an `isinstance` check against the FastAPI class, which silently matched nothing and
dropped every report, surfacing as "at least one output report must be uploaded" on a
form that plainly had them. Test against the base class.

### Pending

- The demo services were running against a database that predates `artifact_types`;
  reseed before the next walkthrough.
- Everything under "Outstanding, needs the user" above.

### Blockers

None.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 1 — UI mock built)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 1 · **Status:** mock complete,
walkthrough pending.

### What was completed

- Restructured `ui-mock/` → `mock/` with `shared/`, `user-ui/`, `admin-ui/` (ADR-013),
  at the user's request, so the two apps are separate mocks.
- `mock/shared/styles.css` (ui2 tokens: light, dark, and the active `light-blue-yellow`
  palette) and `mock/shared/app.js` (sidebar, icons, theme, toast, tabs, modal, drawer).
- user-ui: Runs (live stage progress, queue position), New run (drop zones, copy from
  previous, duplicate-inputs dialog with required rerun reason), Review (traceability
  matrix, findings with OK / Not OK + comments, bulk-OK low, evidence drawer with masked
  sample rows, edit requirement / link modals, waterfall with breaks, attribute explorer,
  Generate gated on High decisions), Final report (frozen, PDF, clone), Run stats, Config
  history (view JSON, copy into new run).
- admin-ui: Report templates + named values, Checks (describe → propose → test →
  activate; judgment flagged "use sparingly"), Compliance & reverse-pass scope,
  Reference data (aliases, masked columns), Usage.
- Docs: phase-1 checklist ticked (criteria 1–3), phase-plan, README, standards, CLAUDE.md
  point to `mock/`; ADR-013 added.
- Verification: `node --check` on all scripts (shared + inline) clean; PII-pattern grep
  clean; launcher rendered in headless Chrome and looked right. Per-page headless
  screenshots could not be captured (Chrome hung on repeat launches), so the pages have
  not been visually checked in a browser yet — the user's walkthrough is that check.

### Pending

- Stakeholder walkthrough (acceptance criterion 4) and feedback capture.
- Phase 0 PR merge; creation of `dev`.

### Blockers

None for the walkthrough.

### Next concrete action

See "Resume here".

---

## Session: 2026-09-18 (Phase 0 — repo setup)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 0 · **Status:** deliverable complete,
PR opened.

### What was completed

- Settled the repo layout: CLAUDE.md as a router, `standards/`, `docs/` with the phase,
  ADR, and session-log conventions, the static mock, and the `ui2` frontend toolchain.
- Agreed with the user: branching main/dev/feature; CI manual-only; Python 3.10 floor +
  pin; ui2 stack + Vitest; compare-file docs layout + "Resume here" + glossary;
  `src/greenlight_ai/` layout; `docker/` dir + root compose; one phase doc per design phase.
- Created the whole Phase 0 tree (see `docs/phase-0.md` scope). `docs/design.md` is the
  design doc verbatim.

### Pending

- Human review + merge of the PR; creation of `dev`.
- Phase 1.

### Blockers

None for Phase 1. The design-doc open questions block parts of Phases 2, 4, 6 (listed in
`docs/phase-plan.md`).

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2a)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2a complete.

### What was completed

- Phase 1 signed off by the user; ADR-014 (build against `LLM_PROVIDER=mock`, defer the
  Gemma benchmark) and ADR-015 (finalize gate = every High finding decided) recorded.
- Python 3.10.14 installed via pyenv; `.venv` created; Phase 2 runtime dependencies
  (pydantic, httpx, python-docx, openpyxl) added to `pyproject.toml`.
- `parsers/base.py`: `OslParser` / `ConfigParser` / `ReportParser` Protocols and frozen
  value objects (`OslSection`, `OslTable`, `ConfigBlock` with JSON path, `ReportSheet`
  with cell addresses and label lookup).
- `parsers/masking.py`: masked-column matching and value masking applied **at parse
  time**, so an unmasked value never exists downstream (ADR-003).
- `parsers/osl_docx.py` (document-order walk of headings, paragraphs, tables),
  `parsers/config_json.py` (logical blocks with JSON paths, technical-key classification),
  `parsers/reports/xlsx.py` (one class per report kind over one read-only reader).
- `scripts/generate_fixtures.py`: six seeded synthetic cases, each carrying its own
  oracle in `manifest.json` — baseline match, extra state, value mismatch, missing rule,
  missing attribute, counts not reconciling.
- 73 tests, 97% branch coverage. `black`, `flake8`, `mypy --strict`, `pytest` all clean.

### Notable decisions and fixes

- `check_docs.sh` was failing on `main` before this work (grep exit 1 under `pipefail`
  for any link-free markdown file); fixed.
- flake8-bugbear B042 on `ParseError` turned out to be a real defect: forwarding extra
  args to `super().__init__` broke unpickling. Fixed with `__reduce__` and a test, since
  the worker carries exceptions across a process boundary.

### Pending

2b (canonical rule schema and normalizers), then 2c–2f.

### Blockers

None. The real-file shape reference and a local model are still wanted but do not block
2b–2f (ADR-014).

### Next concrete action

Milestone 2b: `rules/schema.py`, `rules/normalize.py`, `rules/derive.py` with tests.

## Session: 2026-09-18 (Phase 2 — milestone 2b)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2b complete.

### What was completed

- `rules/schema.py`: Pydantic models for the canonical rule envelope (`Condition`,
  `Rule`), plus `ConfigElement`, `Trace`, `Evidence`, and `Finding`. Validators reject
  payloads that do not match their `req_type` and verdicts that claim an implementation
  without naming an element, so stage 5 needs no defensive checks. `extra="forbid"`
  stops a hallucinated key from passing validation.
- `rules/normalize.py`: state names to codes (all 50 plus DC and territories),
  `AliasTable`, `Interval` carrying boundary inclusivity explicitly, and `parse_number`
  for the forms specs actually use (`1,000,000`, `$40,000`, `60%`).
- `rules/derive.py`: derived report checks per operator, including the inversion that
  turns `age < 21 -> reject` into `accepts.age.min >= 21`.
- 165 tests, 98% branch coverage. All four gates clean.

### Notable decisions

- `Interval` keeps inclusivity separate from the bound because operator mismatch is its
  own finding type; `same_bounds_as` distinguishes a value mismatch from an operator one.
- An OR of conditions derives no report check: either branch may be satisfied, so neither
  bounds the delivered population. A wrong check would be worse than none.
- An unparseable condition value derives nothing rather than a guess; the rule is already
  visible as low-confidence.
- `AliasTable.resolve` returns the normalised input for an unknown name instead of
  raising, so an unknown attribute fails to match and becomes a finding.

### Pending

2c (LLM adapter, cache, prompts), then 2d–2f.

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2c)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2c complete.

### What was completed

- `llm/settings.py`: every knob from `.env`, validated at load time, failing with the
  offending key named.
- `llm/client.py`: the `LLMClient` Protocol, `LLMResult`, the typed error hierarchy, and
  `CallRecord` / `CallLog` (ids and counts only, no prompt text).
- `llm/cache.py`: key = sha256(content) + model + prompt version, with in-memory and
  SQLite backends behind one Protocol so Phase 3 can swap in Postgres.
- `llm/base.py`: the shared path every provider inherits — check the cache, enforce the
  run budget, send, recover JSON from fenced or prose-wrapped answers, validate against
  the schema, retry exactly once with the validation error appended, record the call.
- `llm/openai_compat.py`, `llm/anthropic.py`, `llm/mock.py`, `llm/factory.py`.
- `llm/prompts/`: registry plus five versioned templates (stages 2, 3, 4, 8, 9), each
  with two or three worked examples and a Pydantic output schema.
- 282 tests, 97% branch coverage. All four gates clean.

### Notable decisions

- Prompt templates use `$name` placeholders rather than `{}`: every prompt embeds worked
  examples of JSON output, and brace formatting treated those braces as placeholders.
- The cache key includes the output schema name. The same prompt asked for a different
  shape is a different call, and serving the old answer would return the wrong shape.
- Error messages never echo a response body. A provider's 4xx body can quote the prompt.
- The mock returns empty-but-valid payloads rather than invented requirements: a mock
  that fabricates findings would make a passing pipeline test meaningless.
- An autouse fixture blocks the socket layer for the whole suite. The injected transports
  prove the happy path; blocking sockets proves there is no other path.
- Prompt versions are provisional until the first real-model run (ADR-014); expect a bump.

### Pending

2d (stages 1–5), 2e (stages 6–9), 2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2d)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2d complete.

### What was completed

- `pipeline/context.py`: `RunContext` (the object a run threads through its stages),
  `StageRecord` per-stage status and timing, the re-check stage list, and the
  finalize-gate check (ADR-015).
- Stages 1–5: parse; extract requirements one OSL section per call; describe config
  blocks one per call with technical blocks classified in code and skipped; trace with
  a code-first shortlist and exact-match link, judge only for unclear pairs; compare
  sets, intervals with their operators, attribute lists, waterfall order, and quantities.
- `pipeline/run.py`: orchestrator recording status, duration, calls, cache hits, and
  tokens per stage; resume from the last good stage; `recheck()` reruns stages 5–7 only
  and asserts it makes no LLM call.
- 341 tests, 94% branch coverage, including the design doc's worked example end to end
  (OSL {IL, AZ} vs config {IL, AZ, TX} reports TX as extra) and a direct test for every
  comparison branch.

### Notable decisions and fixes

- ADR-016: waterfall order is compared on shared steps only. Comparing the lists
  literally reported a mismatch on every run, because a config's step list carries
  boundary markers the OSL never mentions.
- The judge prompt now always carries the element's type and payload, not just its prose
  description: "the processing order" does not tell a judge which requirement family a
  block belongs to.
- The stage 4 shortlist falls back to type-only when no field name matches, so a missing
  alias surfaces as a weak trace rather than masquerading as "no config rule".
- Building the fake judge exposed the same trap in test form: matching on `req_type`
  alone linked a score requirement to an age rule. The responder now discriminates on
  the attribute, as the real prompt instructs.
- A stage that fails records itself as failed before the error propagates, so the run's
  own record says where it stopped.

### Pending

2e (stages 6–9 and the expression evaluator), 2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2e)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** 2e complete; all
nine stages now run end to end.

### What was completed

- `checks/expressions.py`: a safe evaluator for admin-authored check expressions. Walks
  a parsed AST and permits only comparison, arithmetic, and four pure functions. No
  `eval`, no attribute access, no comprehensions, no `**`.
- `checks/named_values.py`: cell and label-lookup resolution, with number coercion for
  the forms report cells actually hold.
- `checks/definitions.py`: `CheckDefinition`, `ComplianceRule`, `ReversePassCategory`,
  and the shipped default categories.
- `checks/reports.py`: the fixed per-`req_type` report checks.
- Stages 6 to 9: scoped reverse pass plus compliance presence; report checks and admin
  expression checks; second-opinion verification; the summary.
- 475 tests, 94% branch coverage. All four gates clean.

### Notable decisions and fixes

- The report checks were resolving attribute names with plain normalisation, so a DIRT
  column named `SCORE_V3` never matched an OSL requirement about "score" and every
  bound check reported "could not evaluate". They now resolve through the alias table
  on both sides. This is the bug the alias table exists to prevent.
- `step_order` is not a report check. The counts report shows totals per step, not the
  order they ran in, and order is settled between the OSL and the config in stage 5.
  Treating it as a report check produced a spurious finding on every run.
- A disputed finding is downgraded to Review and kept, never dropped: the model may
  reduce false positives but must not be able to hide a real problem.
- A failed verification or summary leaves the run intact. Both are improvements on the
  findings, not gates over them.
- Admin configuration moved onto `RunContext` so the orchestrator can call every stage
  with one uniform signature; Phase 3 fills it from the database.

### Pending

2f (CLI and golden set).

### Blockers

None.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 2 — milestone 2f; Phase 2 complete)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 2 · **Status:** complete except the
deferred real-model benchmark.

### What was completed

- `src/greenlight_ai/cli.py`: `greenlight-ai run` with `--osl`, `--config`, repeatable `--report
  KIND=PATH`, `--out`, `--provider`, `--cache`, `--stage`, and `--log-level`. Writes a
  findings document carrying the summary, per-severity counts, per-stage statistics,
  the finalize-gate state, and every finding with its evidence.
- `scripts/synthetic_model.py`: the scripted stand-in that answers each LLM stage by
  reading the prompt. Lifted out of the test conftest so the golden set and the suite
  drive the pipeline identically.
- Golden set expanded to 12 cases covering every finding type in the design doc's table,
  each carrying its oracle in `manifest.json`.
- `scripts/golden_set.py`: scores recall and precision per finding type and per case,
  writes a Markdown report, and exits non-zero on a regression so CI can gate on it.
- `docs/benchmarks/`: the synthetic baseline, 12 / 12 cases, and a README stating plainly
  what that number does and does not prove.
- 505 tests, 95% branch coverage. All four gates clean.

### Notable decisions and fixes

- The CLI exits 0 for a run that completes and finds problems, and non-zero only when
  the run itself fails. A wrapper has to be able to tell "the delivery is wrong" from
  "the check did not happen".
- A failed run still writes its document, carrying the stages that completed and the
  error, so a caller can see how far it got.
- `run_command` takes an optional client, which is the seam the golden set injects the
  scripted stand-in through. No fixture-aware code lives in `src/greenlight_ai/`.
- The scripted model could not read a filter whose threshold is stored in `value`
  rather than `min`, which cost one golden-set case. Fixed in the responder, since a
  real model would read both spellings.

### Pending

Phase 2 acceptance criterion 2: the real-model golden-set run. Everything else is done.

### Blockers

The real-model run needs a local model or an API key from the user (ADR-014).

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (documentation currency pass)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** between 2 and 3 · **Status:** docs
brought current; no code change.

### What was completed

- Marked phases 0, 1, and 2 complete: every scope box and acceptance criterion ticked in
  `phase-0.md`, `phase-1.md`, and `phase-2.md`, with dated status lines. Two boxes stay
  deliberately unticked and are labelled: phase-0 exit criterion 6 (a human merges the PR
  and creates `dev`) and phase-2 acceptance criterion 2 (the real-model benchmark,
  ADR-014).
- Gave every phase doc and both master tables the same status vocabulary
  (⬜ not started · 🟡 in progress · ✅ complete).
- Removed every reference to the other repositories we looked at during setup. The
  decisions they informed are stated on their own merits in the ADRs; the provenance was
  noise that would age badly. `compare-file` survives only where it is a live
  instruction, such as the ui2 theme tokens the mock copies and the report format.
- Added the rules that keep this from drifting again, in `CLAUDE.md`: a "Finishing a
  phase" checklist, a "documentation is always current" rule, an instruction to grep for
  a name before renaming it, and two more steps in the definition of done (ADRs written,
  `check_docs.sh` passing, commit actually pushed).
- Recorded two more open questions in `phase-plan.md`: the waterfall step-name aliases
  that ADR-016 raised, and which model the golden set should be benchmarked against.

### Pending

Phase 3.

### Blockers

None for Phase 3. The items under "Resume here" need the user but do not block it.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 3 — web app)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 3 · **Status:** complete, with the
compose run unverified.

### What was completed

- **ADR-017**: `DATABASE_URL` selects the backend. SQLite is the default, so a test, a
  migration, or a single run needs no Docker; Postgres is what compose configures.
  Procrastinate is dropped — it is Postgres-only — and the queue is now an ordinary
  `jobs` table. That removed a dependency rather than adding one, and there is still no
  Redis.
- `db/`: all 21 tables, portable column types, session helpers with the SQLite pragmas
  that make foreign keys and concurrent reads behave, the job queue, the DB-backed LLM
  cache, the repository, and an Alembic migration that round-trips on SQLite.
- `worker/`: the polling loop, `run_pipeline` / `recheck` / `purge`, retries with
  backoff, and stale-claim recovery so a killed worker's job is picked up by another.
- `api/`: the full `/api/v1` surface, upload validation, the single auth seam, and audit
  writes.
- `user-ui/`: Next.js 15 with all five Phase 3 screens, the ui2 theme, the `/api/*`
  rewrite proxy, a standalone Dockerfile, and 35 Vitest tests.
- 602 Python tests and 35 frontend tests; every gate clean.

### Notable decisions and fixes

- `get_data_dir` read the environment instead of application state, so an injected data
  directory was silently ignored. Found by a test that asserted the files actually
  landed on the volume.
- A live run against an empty database exposed a real defect: with no alias configured,
  stage 5 reported "Config has no condition on score" because the config calls it
  `SCORE_V3`. Stage 4 had already decided the element implements the requirement, so
  stage 5 now pairs a single condition on each side when the alias table has never heard
  of the attribute. The guard is narrow: a *known* attribute with no counterpart is
  still a real gap.
- A run awaiting a retry stays `queued` rather than flashing `failed` in the UI; only a
  dead job marks the run failed.
- The Runs list stops polling when nothing is queued or running.

### Pending

Phase 4, then Phase 5.

### Blockers

None. The compose run needs a machine with Docker.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phases 4 and 5 — admin-ui and the final report)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phases:** 4 and 5 · **Status:** both
complete, with two criteria unverifiable on this machine.

### Phase 4 — admin-ui and configurable checks

- The admin backend: report templates, named values with live resolution against the
  uploaded samples, versioned checks, compliance rules, reverse-pass categories,
  aliases, masked columns, and a usage dashboard that is plain SQL over the run tables.
- `POST /admin/checks/draft` is the only model call in the admin flow and happens once
  per check; testing a check never calls it.
- `admin-ui` on :3001, same toolchain and theme as user-ui, with all five screens.
- Added `validate()` to the expression evaluator. `referenced_names` only parsed, so
  `__import__('os')` could be *saved* and would have failed only at evaluation time.
  Saving now walks the same node rules the evaluator uses.

### Phase 5 — the frozen report

- A self-contained one-page HTML report: inline CSS, no network, opens from `file://`.
  Rendered once, hashed, stored, and never regenerated; a second finalize is a 409 and
  re-reviewing a finalized run is refused, so the file always matches the decisions it
  came from.
- The PDF is rendered from the **stored file**, behind a Protocol so the api depends on
  the capability rather than on Playwright. Playwright is the optional `[pdf]` extra,
  installed in the worker image; without it the endpoint returns 503 naming the HTML
  report rather than failing the download silently.
- The user-ui final report screen shows the stored page in an iframe rather than
  re-implementing it, so there is only ever one version of the document.

### Notable decisions

- Guards worth keeping: a named value a check still uses cannot be deleted; saving one
  reverse-pass category seeds the rest, so switching one off cannot silently enable the
  others; adding a masked column keeps the shipped defaults (ADR-003).
- Judgment checks have a prompt and a schema, and the UI flags them "use sparingly",
  but the worker still skips them: an expression check costs nothing and a judgment
  check costs a call per run, so wiring it in waits for a real need. Noted in
  `phase-4.md`.
- The report template uses `StrictUndefined`. A silently blank field in a frozen report
  is a defect nobody can fix afterwards, so a missing value fails at render time.

### Pending

Phase 6, and the user items under "Resume here".

### Blockers

None for Phase 6, though most of it wants the real file samples.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 6 — hardening, and the demo)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 6 · **Status:** in progress —
everything doable from a development checkout is done.

### What was completed

- **ADR-018, the PII tripwire.** Every assembled prompt is scanned inside the adapter,
  before the cache and therefore before any path to the network, and a match **raises**
  rather than warns. The patterns match formats, not meanings, and a test asserts that
  ten samples of real pipeline text pass: a tripwire that fires on ordinary content
  gets switched off, which is worse than not having one. Matches are reported by
  pattern name and a redacted shape, never the value.
- Retention: the worker schedules its own 24-hour sweep, so no cron entry is needed,
  and `scripts/purge.py --dry-run` reports what would go before anything does.
- Audit completeness and log safety, both asserted by tests rather than reviewed by eye.
- `scripts/load_test.py`, and `scripts/seed_demo.py` which loads admin reference data
  plus eight runs covering every lifecycle state.
- The deployment checklist in `deployment.md`, with the in-house items marked as such.
- 731 Python tests, 35 user-ui, 10 admin-ui. Every gate clean.

### What the load test found

A real race, which is what a load test is for. Two workers on different runs reach the
same cache key — the key is a content hash, so an identical OSL section in two runs
produces one — both miss, both call the model, and both insert. The loser got a unique
constraint violation and **its run failed**. Three of twelve runs died under four
workers.

A cache write is an optimisation. Failing a run over one trades a saved call for a lost
run, which is the wrong way round. `DbCache.put` now treats a duplicate as what it is —
another worker stored the same answer for the same content — and any other write error
as a warning. Twelve of twelve now pass, and `tests/db/test_concurrency.py` covers it.
This would have happened on Postgres too.

### What the demo found

Bringing the UI up against real data showed three things the tests could not:

- Finished runs rendered an empty grey progress bar, because the list endpoint does not
  carry per-stage records. They now report their outcome instead.
- The failed run read "Failed at s1_parse: PipelineError: s1_parse: …" — the stored
  error already names its stage.
- With one day of history the usage sparkline filled the card edge to edge and read as
  a rendering fault. It now caps the bar width until there are enough points.

### Pending

The Phase 6 items that need real files, the in-house model, or the platform and
compliance teams. They are marked **in-house** in `phase-6.md` and listed under
"Resume here".

### Blockers

None that are mine. Everything left is on the user's list.

### Next concrete action

See "Resume here".

## Session: 2026-09-18 (Phase 7 — documented, dormant)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 7 · **Status:** documented only, as
asked. No code was written and nothing was started.

### What was completed

- `docs/phase-7.md`, "Real-world fit": the phase that runs on the machine holding the
  real OSL, config, and reports, and only when the user asks for it.
- ADR-019 recording why it is a separate phase rather than part of Phase 6: it happens
  on a different machine, at an unknown time, driven by files that cannot come here,
  and it is conversational rather than planned. Folding it into Phase 6 left a phase
  that could never be completed.
- Both phase tables, `CLAUDE.md`, and the README index updated. `CLAUDE.md` says
  plainly that a session must not act on Phase 7 because it noticed it exists.

### What is in the doc

- **The one rule** first, before anything else: a real customer file, or anything
  derived from one, never enters the repository. A table of what may come back out
  (shapes, counts, patterns, synthetic fixtures modelled on a shape) against what may
  not (any value, any row, any identifier), and an instruction to keep the real files
  outside the working tree.
- **How to invoke it** and the loop Claude runs each time: read the file with the
  existing parser, name the gaps specifically, say what changes and where and why,
  say what does *not* change, propose the fixture, then stop and wait.
- **Per-artifact assumption tables** — for the OSL, the config, and the reports — each
  row naming what the parser believes today and what would break it. These are derived
  from the code, which is what makes the analysis start from what the tool actually
  does. They go stale when a parser changes, and the ADR says who updates them.
- **Where changes will land**, with a note that a change reaching `pipeline/` or
  `rules/schema.py` is a signal that a design assumption was wrong, not a parsing detail.
- Bootstrap steps for the new machine, including taking a golden-set baseline *before*
  touching prompts, so a later accuracy drop is visible.

### Pending

Nothing. The phase is dormant until the user asks for it.

### Blockers

None.

### Next concrete action

See "Resume here". Phase 7 is not it.

## Session: 2026-09-18 (PDF download fix)

**Branch:** `claude/funny-cerf-jsyvpe` · **Status:** fixed and verified with a real
browser. Phase 5 is now complete on every criterion.

### The report

Clicking "Download PDF" saved a JSON file.

### What was actually wrong — three things

1. **Playwright was not installed**, so the endpoint correctly answered 503 with a JSON
   body explaining that. Installed it and Chromium; PDFs now render.
2. **The UI could not tell.** It used a plain `<a href download>`, which has no way to
   check a status: it saved the 503 body under the name the user expected. It now
   fetches through the API client, which raises on a non-2xx and on a 200 that is not a
   PDF, and only a real document reaches the disk. The run detail carries
   `pdf_available`, so the button is disabled with an explanation rather than failing
   after the click.
3. **The PDF was missing its content**, which only showed up once one could be made:
   one page, 1021 characters, every section a heading with nothing under it. The print
   rule `details .body { display: block }` cannot work, because a closed `<details>`
   hides its children through the browser's own mechanism rather than through a style.
   The report now sets `open` on every section before printing, and the renderer does
   the same itself so an already-frozen report still prints in full. Two pages, 3147
   characters, all seven matrix rows, every reviewer comment.

Two smaller things the verification caught: the disclosure arrow printed, because
`details[open] summary::before` outranked the rule meant to hide it; and identifiers
wrapped mid-token, so `R-001` arrived in the PDF as `R-` and `001`.

### A note worth keeping

Run 9 had already cached a PDF from the broken renderer. The HTML is the frozen record
and must never be regenerated (ADR-005), but the **PDF is a rendering of it** —
re-rendering the same HTML gives the same document. So after fixing a renderer, delete
`data/reports/*.pdf` and they rebuild. That is now a line in the deployment checklist
and a comment at the point in the code where the decision is made.

Run 9 also demonstrated the freeze working as intended: its stored HTML predates the
template fix and still carries the old stylesheet, while its PDF now prints in full
because the *renderer* opens the sections. That is why the fix went in both places.

### Tests

Four regression tests on the API side and four in the UI client, covering the exact
shape of the bug: a 503 must be an unmistakable status with a non-PDF body, a 200 must
be a real PDF with a filename, and the client must raise rather than hand back bytes in
either failure case. 732 Python tests, 39 user-ui, 10 admin-ui.

---

## Session: 2026-09-20 (the real model, and Phase 6.14 specified)

**Branch:** `dev`, synced to `900f301`. **Phase:** 6.13 complete; 6.14 specified, not
started. **Status:** documentation only — no source file changed.

**Completed.**

- **The adapter ran against a real model for the first time.** `LLM_PROVIDER=anthropic`
  with Claude Haiku 4.5. The model id in `.env` was corrected from a dated spelling to
  the canonical `claude-haiku-4-5`; both were tested against the live endpoint and both
  answer, but the model name is part of every cache key (ADR-005) and the undated form
  is the one to keep. No code changed: the Anthropic client already sent the right
  shape. A full run took 33s, 30 calls, 30,233 in / 2,792 out, about $0.045, and
  reproduced on the real model exactly what the fixture plants. Stages 5, 6 and 7 made
  **no calls at all**, which is ADR-001 visible in a log.
- **A gap in the documented startup.** Nothing in `src/` loads `.env`; the commands in
  "See it running" start the worker on the built-in defaults, so it logs
  `building mock client (model=gemma3:27b)` and produces findings that read as real.
  The block below now exports `.env` first.
- **An identity mismatch was submitted deliberately, and passed.** Wrong customer, wrong
  configuration id, a credit date in none of the artifacts. Only the credit date was
  caught, at stage 7 of 9. `config.json` declares both `configuration_id` and
  `customer`; the parser reads the first and ignores the second, and neither is ever
  compared with what the submitter typed. Delivery drift then reported "no earlier
  finalized run of configuration CFG-DOES-NOT-EXIST-999", which is indistinguishable
  from a legitimate first run.
- **[`phase-6.14.md`](phase-6.14.md) written** from that result: the artifact match check, the
  credit date resolved by scoped label, one register and one marker for every field that
  reaches the model, tooltips on by default, and the theme locked by default.
- **A standing touchpoint added to `CLAUDE.md`:** a commit that changes what reaches the
  model, what a stage reads, or a cap, updates `docs/model-context.md`, the field's
  label or tooltip in both apps, and the training documents — in that commit.

- **ADR-041 written**, recording the three decisions the user took on the phase before it
  was built: an administrator accepts an identity mismatch, the gate does not cross-check
  run history, and an accepted mismatch does not block the finalize gate. The third is a
  deliberate departure from ADR-035 and the ADR says why — a coverage gap is a question
  the tool cannot answer and must put to a person at the last moment; an identity
  mismatch was already asked and answered by a named administrator before the run
  started, and asking twice trains people to click through both.

**Pending.** Every 6.14 box.

**Blockers.** None.

**Next concrete action.** Cut `feature/identity-gate` from `dev` and start 6.14a.

**Housekeeping.** `data/demo.db` was re-seeded on the 6.13 schema; the previous file is
`data/demo.db.pre-6.13.bak`. The demo database is built by `create_all` and carries no
alembic stamp, so `alembic upgrade head` fails against it — re-seed rather than migrate.
`pytest` is 1222 passing on `900f301`.

---

## Session: 2026-09-20 (Phase 6.14 — the artifacts belong together)

**Branch:** `feature/artifact-match`. **Phase:** 6.14, partly built. **Status:** 1292
tests pass; `black`, `flake8`, `mypy`, both UI gates and `check_docs.sh` clean.

**Completed.**

- **6.14a, the artifact match check — complete.** Code compares the submitted
  configuration id and customer against what the uploaded configuration declares, before
  the model is asked anything. A submission whose artifacts agree queues exactly as
  before; one whose artifacts disagree is `held` with its files intact. Anyone who can
  submit can accept, with one reason covering every mismatch and four common reasons one
  click away. The worker refuses a `held` run so a replayed job cannot race the gate, and
  the waiver is rendered on the frozen report.
- **6.14e, the theme locked — complete.** `ui.theme_locked` defaults on; both training
  documents corrected in the same commit, since both described a picker every user could
  reach.
- **6.14b, partly.** `field_labels` with the scope vocabulary, `resolve_labels`, and a
  stage-7 check that finds the labelled cell and **compares** it — so it can now report
  "the reports are cut as of 2026-03-31, not the 2026-04-30 you gave", which the old
  search over every value could never say. Where no labelled cell exists the old search
  runs and the finding says it is the weaker one.
- **6.14c and 6.14d, partly.** `docs/model-context.md` is the register of every field a
  person can write; `<FieldEffect>` states what a field does and never hides;
  `<Explain>` is help and hides behind `ui.tooltips`, on by default.

**Pending.** Four items, each labelled **outstanding** in `phase-6.14.md`: an admin
screen for `field_labels` (a new label is a database row today); version history and
revert for labels; the remaining field markers and tooltips beyond Artifact types and
Delivery programmes; the live cap countdown; and moving the credit date into the
pre-flight, which needs every report parsed at submit and is worth measuring first.

**Blockers.** None.

**Next concrete action.** Close the outstanding items, starting with the admin screen
for `field_labels`.

**Worth knowing.** The drift tests now walk the accept path: forcing two fixtures to
share one configuration id is exactly the disagreement 6.14a catches, so the test does
what a person would rather than being exempted from the gate.

---

## Session: 2026-09-21 (6.14 closed out, and the availability controls)

**Branch:** `feature/queue-controls`. **Phase:** 6.14, complete but for one deferred
item. **Status:** 1335 tests pass; `black`, `flake8`, `mypy`, both UI gates and
`check_docs.sh` clean.

**Completed.**

- **Field labels are versioned** (closing 6.14b), per canonical field with revert, the
  way worked examples are versioned per stage. The useful question is what we called
  the credit date last month, not what happened to row 14.
- **Every admin screen explains itself** (closing 6.14d), through an `explain` slot on
  `PageHeader`. Each one names what belongs *elsewhere*, taken from the overlap table in
  `admin-training.md` — which is the part that helps somebody choosing between sixteen
  surfaces.
- **6.14j, availability.** Four switches resolved by one module so a deployment can
  never refuse submissions while the banner says everything is fine: a change-your-mind
  window, hold the queue, stop accepting submissions, and maintenance mode. The window
  reuses the queue's existing `run_after` rather than adding a mechanism. Cancelling is
  free while a run is queued and keeps the files, so the next step is cloning it
  corrected. Work already running always finishes.

**Pending.** The live cap countdown in 6.14c — deferred by the user as a nice-to-have.

**Blockers.** None.

**Next concrete action.** Open a PR into `dev`, then report before starting anything
new.

**Worth knowing.** Adding the grace window broke 81 tests at once, because the suite
drives the worker inline and immediately. The fix is an autouse fixture setting the
window to zero rather than changing the default: the default is a product decision and
a test environment is not where it gets made. The tests that are *about* the window set
it themselves.

Also: a dev server left running across a `git checkout` corrupts its `.next` cache and
serves a blank page on HTTP 200. Clear `.next` and restart after switching branches,
and check rendered content rather than a status code when verifying the apps are up.

---

## Session: 2026-09-21 (6.15 and 6.16 shipped; what is left gathered into 6.17)

**Branch:** `dev`, level with `main`. **Status:** 1391 tests pass; every Python and UI
gate and `check_docs.sh` clean.

**Completed.**

- **Phase 6.15, both options.** A compliance rule was a substring match that could not
  tell a control that is *absent* from one that is *spelled differently*, and reported
  both at HIGH. Option C widens the match with four deterministic tests; option A asks
  the model *where* a control is when C still fails, and code refuses a path it did not
  offer, an answer below a confidence floor, any verdict but `found`, or no answer at
  all. A located control is a review-severity question, never a pass.
- **Phase 6.16.** A thirty-day run count and the delivery programme on the runs screen;
  `Finding.engine` saying whether code or the model reached each answer; a dated report
  of orders validated and manual hours displaced, which states on its face that the
  hours figure was supplied rather than measured.
- **Option B from 6.15 measured and deliberately not built.** Named values are brittle
  the same way, but fail *safe* — `could_not_evaluate` at review severity, not a false
  HIGH. One problem turned out to be two with different severities, and the severe one
  was already closed. What remained was worth normalising the label lookup, not a new
  authoring surface.
- **Two stale console claims corrected.** Compliance and Checks both said "nothing here
  is sent to the model"; 6.15 and 6.13d respectively had made that false. A test now
  fails on any screen-wide claim of that kind.
- **6.14's acceptance criteria closed.** All twelve were met and tested and none had
  been ticked. Each was verified against a named passing test before ticking; the one
  that had stopped being true as written was corrected rather than ticked.

**Pending.** [`phase-6.17.md`](phase-6.17.md) — the programme keyword check is the one
surface never measured for the brittleness two others were; the deferred cap countdown;
how scope reaches the compliance locator; and the two standing touchpoints that have
fallen behind.

**Blockers.** None.

**Next concrete action.** 6.17a: measure the programme keyword check.

**Worth knowing.** Three times now a measurement has changed the plan rather than
confirmed it — the nesting row in 6.15 was not the mechanism the specification claimed,
segment matching alone would have been a regression, and option B turned out not to be
worth building. Measuring first is cheap and it has yet to be wasted.

# Phase 6.12 — One front door, and one way to say where a rule applies

**Status:** ✅ **complete** — 2026-09-20, specified and built from the review that produced
Phase 6.11. That review found sixteen places an administrator can tell the tool
something and three different vocabularies for saying where it applies. Both are
consequences of building the right thing sixteen times rather than of building the
wrong thing once, and both are now the main obstacle to somebody new being useful.

**Goal:** two things, and deliberately not a third.

1. **A front door.** One place where an administrator writes what they want the tool to
   check, in their own words, and the model works out which of the existing surfaces it
   belongs on and drafts it there. They confirm it into shadow. Nothing new runs; the
   draft lands on the surface that already ran it.
2. **One scope vocabulary.** "Everywhere", "this programme", "this customer" — said the
   same way in the API, the screens and the documents, whatever table it is stored in.

**Not** a rewrite of the sixteen screens. They are the expert view and they stay. A
front door that replaced them would trade an administrator's ability to see exactly what
runs for the convenience of not having to.

Effort 1–2 weeks. Read `docs/phase-6.11.md` "The idea", ADR-021 (the model proposes, a
person approves, shadow before it counts) and ADR-029 (scope is one token) first.

## The problem, stated precisely

**Sixteen surfaces.** An administrator who wants the tool to check something has to know
which of these it is: an artifact type's AI context, a validation guide entry, a meaning
entry, a named value, an expression check, a judgment check, a compliance rule, a
programme rule, a programme keyword, a standing instruction, a configuration note, a
field constraint, a learned rule, an alias, a masked column, or a reverse-pass category.
Each is the right home for what it holds. Nobody new can be expected to pick.

The overlaps are real, not apparent:

| These all do this | And differ in |
| --- | --- |
| Validation guides, meaning entries, named values | how they locate a report cell |
| Programme rules, compliance rules, judgment checks | who evaluates "this must hold" |
| Artifact AI context, standing instructions, configuration notes | nothing, at the prompt: all three land in the same block |

**Three vocabularies.** `scope_code` on programme rules, meaning entries and samples; a
`scope` string of `all` · a customer name · `programme:CODE` on checks, compliance rules
and field constraints; `customer_name` on aliases. ADR-029 already says scope is one
token. It is one token in three shapes.

## The shape of the answer

### The front door proposes; nothing new evaluates

The front door is the training loop pointed at an administrator instead of a reviewer.
It reuses what ADR-021 already built and adds one step in front of it.

```
a sentence ──classify──▶ which surface ──draft──▶ candidate ──confirm──▶ shadow ──activate──▶ active
              (model)      (model)                 (code validates)      (a person)
```

The model answers two narrow questions, both schema-constrained: **which surface** does
this belong on, and **what is the rule** in that surface's own shape. Code validates the
draft exactly as it validates a synthesized one, the critique pass of 6.11g reads it
back against the sentence, and it lands as a `rule_candidate` an administrator confirms.
There is no new evaluator, no new rule table and no new lifecycle: that discipline is
ADR-021's and it is what keeps one place to look when a finding is wrong.

A statement the model cannot place comes back saying so, with its reasoning, and the
administrator picks the surface themselves. A statement that is not a rule at all —
background, a note, an instruction — is classified as such and offered to the surface
that holds background, never forced into a rule.

### One scope vocabulary, without a risky migration

One token, three storage shapes, and one module that is the only thing that knows this:
`scopes.py` parses any stored form into a `Scope`, formats it back, and answers "does
this cover that run". Every reader goes through it; nothing else parses a scope string.
The API and both screens speak the token. A data migration that rewrote three columns
across a dozen tables would be the riskiest change in the product for a cosmetic gain,
so it is not done: the vocabulary is unified where people meet it.

## Scope · ✅ complete

### 6.12a — One scope vocabulary · ✅ complete

- [x] `greenlight_ai/scopes.py`: a `Scope` value object (`everywhere`, `programme:CODE`,
      `customer:NAME`, and `config:ID` — see "Found on the way"), `parse` accepting every
      stored form, `token` rendering the canonical one,
      `covers(customer, programme, configuration)` answering the only question anyone
      asks, and `label()` for a screen.
- [x] `checks/definitions.in_scope` and every other reader delegate to it. It is the
      single place a scope string is interpreted; a grep for `programme:` outside
      `scopes.py` finds nothing.
- [x] The API accepts and returns the canonical token everywhere, and still accepts the
      older forms on input, because an administrator's bookmark and an in-flight request
      are not a reason to break anything. One pydantic type (`ScopeToken`) does it in
      both directions, so no router has to remember.
- [x] One scope control, in the console that has one. The user app has no scope control
      and gains none: the "scope" it shows on a run is the delivery programme that run
      belongs to, which is a different thing that happens to share a word.
- [x] Tests: every stored form parses to the right `Scope`; a programme scope never
      covers another programme or a run with no programme; the canonical token
      round-trips; the old forms still work on input; the same list is asserted again in
      the console, because two files have to agree.

### 6.12b — The front door · ✅ complete

- [x] One prompt, `admin_classify`, answering which surface a statement belongs on and
      why, from a closed set, with a confidence and a question when it cannot tell.
      Registered and covered by the prompt suite; the statement reaches it as delimited
      data, never as instruction (ADR-021).
- [x] `POST /admin/front-door`: a sentence and an optional scope, and back a candidate
      on the surface the model chose, or an open question. It reuses
      `training.synthesis` for the drafting, the validation, the fingerprint, the
      conflict check and the critique pass. No second path into the rule tables.
- [x] A statement that is background rather than a rule is classified as such and
      offered to the artifact context or the standing instructions, not forced into a
      rule that would then be wrong.
- [x] Admin console: one box on a new **Tell the tool** screen — the sentence, the
      scope, and what it became, with a link to the surface it landed on so the expert
      view is one click away and stays the place where things are really managed.
- [x] Every candidate the front door creates is indistinguishable from one synthesis
      created, including its provenance, so the Rules screen needs no new column and
      the approval path needs no new branch.
- [x] Tests: a field statement becomes a field constraint; a cross-report statement
      becomes a check; a "must be in the configuration" statement becomes a compliance
      rule; an unclassifiable one comes back with the question and creates nothing; an
      instruction aimed at the model does not change the shape of what is drafted.

### 6.12c — Documentation and tests · ✅ complete

- [x] ADR-037: the front door classifies onto existing surfaces and never adds one; one
      scope module rather than a migration.
- [x] `design.md` (the admin screen table), `architecture.md` (the `scopes` module and
      the front door), `glossary.md`, `llm-privacy.md`, `admin-training.md`. The user
      document needed nothing: neither the front door nor the scope vocabulary is
      visible from the user app, and changing its date to say otherwise would be a lie.
- [x] The overlap table above kept in `admin-training.md`, because the honest answer to
      "which of these do I use" is a table, and the front door does not remove the need
      for one.

## Acceptance criteria · ✅ complete

1. [x] A scope written in any stored form parses, covers the right runs, and renders as
   the same token in the API and the console.
2. [x] Nothing outside `scopes.py` interprets a scope string, and nothing outside
   `scope-picker.tsx` interprets one in the console.
3. [x] An administrator types "the account review file must never have a blank
   origination date" into the front door and gets a field-constraint candidate, which
   the ordinary approval path lands in shadow on the existing screen.
4. [x] An administrator types "billing count must never exceed the delivered count" and
   gets an expression check.
5. [x] An administrator types something the model cannot place and gets its question,
   with nothing created — no candidate and no observation.
6. [x] A front-door candidate and a synthesized candidate are handled by the same
   approval path, with the same provenance fields filled.
7. [x] Every existing test still passes.

## Deliberately not in this phase

- **Merging the overlapping surfaces.** Guides, meaning entries and named values could
  be one thing; so could programme rules, compliance rules and judgment checks. Each
  merge is a migration and a behaviour change, and doing them behind a front door that
  already hides the difference would be paying the risk for something nobody sees.
- **Rewriting the sixteen screens.** They are the expert view, and the front door exists
  so that most people never need them — not so that the people who do are left worse off.

## Found on the way

- **There were four stored shapes, not three.** `config:ID`, from a note written against
  one configuration (ADR-024), is a scope like the others and was missing from the list
  in this document's first draft. `Scope` carries it. Nobody picks it — it is inherited
  from where the note was written — so the scope control shows it read-only rather than
  turning it into a customer name.
- **A programme-scoped field constraint never ran.** The loader compared the stored
  string against `all`, the customer name and `config:ID` and nothing else, so a
  constraint scoped to a delivery programme was loaded on every run and matched on none.
  It was not visible as a bug: the rule simply never fired. `load_admin_config` now takes
  the run's programme and asks `scopes.covers`. This is the whole argument for one
  module in one line.
- **`all` was already taken.** The rule schema's `applies_to: "all"` means every record,
  not every run. Two unrelated things spelled the same way, one of them in the LLM's
  output schema, is how a prompt change quietly becomes a scope change; the canonical
  token is `everywhere`.
- **The classification routes; it does not draft.** Passing the chosen surface into the
  synthesis prompt would have meant changing that prompt, bumping its version and
  discarding its cache, to tell it something it already works out. So the front door
  classifies only to decide whether there is a rule here at all, and synthesis picks the
  shape as it always has. When the two disagree the answer says so, which is better
  information for the person approving than either reading alone.
- **A statement that cannot be drafted still leaves a record.** When synthesis returns
  nothing usable, the observation stays in the queue rather than being rolled back.
  Somebody said something; the record of that is worth more than the row it occupies
  (ADR-021), and it can be synthesized later alongside others.

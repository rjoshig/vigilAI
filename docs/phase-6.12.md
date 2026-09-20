# Phase 6.12 — One front door, and one way to say where a rule applies

**Status:** 🟡 **in progress** — specified 2026-09-20, from the review that produced
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

## Scope · ⬜ not started

### 6.12a — One scope vocabulary · ⬜ not started

- [ ] `greenlight_ai/scopes.py`: a `Scope` value object (`everywhere`, `programme:CODE`,
      `customer:NAME`), `parse` accepting every stored form, `token` rendering the
      canonical one, `covers(customer, programme)` answering the only question anyone
      asks, and `label()` for a screen.
- [ ] `checks/definitions.in_scope` and every other reader delegate to it. It becomes
      the single place a scope string is interpreted; a grep for `programme:` outside
      `scopes.py` should find nothing.
- [ ] The API accepts and returns the canonical token everywhere, and still accepts the
      older forms on input, because an administrator's bookmark and an in-flight request
      are not a reason to break anything.
- [ ] Both consoles use one scope control with the same three words in the same order.
- [ ] Tests: every stored form parses to the right `Scope`; a programme scope never
      covers another programme or a run with no programme; the canonical token
      round-trips; the old forms still work on input.

### 6.12b — The front door · ⬜ not started

- [ ] One prompt, `admin_classify`, answering which surface a statement belongs on and
      why, from a closed set, with a confidence and a question when it cannot tell.
      Registered and covered by the prompt suite; the statement reaches it as delimited
      data, never as instruction (ADR-021).
- [ ] `POST /admin/front-door`: a sentence and an optional scope, and back a candidate
      on the surface the model chose, or an open question. It reuses
      `training.synthesis` for the drafting, the validation, the fingerprint, the
      conflict check and the critique pass. No second path into the rule tables.
- [ ] A statement that is background rather than a rule is classified as such and
      offered to the artifact context or the standing instructions, not forced into a
      rule that would then be wrong.
- [ ] Admin console: one box on a new **Tell the tool** screen — the sentence, the
      scope, and what it became, with a link to the surface it landed on so the expert
      view is one click away and stays the place where things are really managed.
- [ ] Every candidate the front door creates is indistinguishable from one synthesis
      created, including its provenance, so the Rules screen needs no new column and
      the approval path needs no new branch.
- [ ] Tests: a field statement becomes a field constraint; a cross-report statement
      becomes a check; a "must be in the configuration" statement becomes a compliance
      rule; an unclassifiable one comes back with the question and creates nothing; an
      instruction aimed at the model does not change the shape of what is drafted.

### 6.12c — Documentation and tests · ⬜ not started

- [ ] ADR-037: the front door classifies onto existing surfaces and never adds one; one
      scope module rather than a migration.
- [ ] `design.md` (the admin screen table), `architecture.md` (the `scopes` module and
      the front door), `glossary.md`, both training documents.
- [ ] The overlap table above kept in `admin-training.md`, because the honest answer to
      "which of these do I use" is a table, and the front door does not remove the need
      for one.

## Acceptance criteria · ⬜ not started

1. [ ] A scope written in any of the three stored forms parses, covers the right runs,
   and renders as the same token in the API and both consoles.
2. [ ] Nothing outside `scopes.py` interprets a scope string.
3. [ ] An administrator types "the account review file must never have a blank
   origination date" into the front door and gets a field-constraint candidate, in
   shadow, on the existing screen.
4. [ ] An administrator types "billing count must never exceed the delivered count" and
   gets an expression check.
5. [ ] An administrator types something the model cannot place and gets its question,
   with nothing created.
6. [ ] A front-door candidate and a synthesized candidate are handled by the same
   approval path, with the same provenance fields filled.
7. [ ] Every existing test still passes.

## Deliberately not in this phase

- **Merging the overlapping surfaces.** Guides, meaning entries and named values could
  be one thing; so could programme rules, compliance rules and judgment checks. Each
  merge is a migration and a behaviour change, and doing them behind a front door that
  already hides the difference would be paying the risk for something nobody sees.
- **Rewriting the sixteen screens.** They are the expert view, and the front door exists
  so that most people never need them — not so that the people who do are left worse off.

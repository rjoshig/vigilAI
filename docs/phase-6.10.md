# Phase 6.10 — Meaning: scoped samples, the mapping interview, and edit/delete everywhere

**Status:** 🟡 **in progress** — decided 2026-09-19; Part A landed 2026-09-19.

**Goal:** the platform holds **global and per-programme meaning**: OSL variants as
scoped samples, each requirement tied to the config block that implements it and the
report cells that evidence it, proposed by the model from the samples and confirmed
by an administrator into rules born in shadow (ADR-021). Alongside, wording is
editable everywhere and every delete is deliberate (ADR-032).

## Overlap, settled

| Surface | Verdict |
| --- | --- |
| Artifact-type AI context (paragraph) | stays, for prose that fits nowhere else |
| Validation guide (per report cell) | becomes Meaning's "by report cell" view |
| Mapping entries (per requirement) | new, the OSL-side twin of a guide entry |
| Named values + checks | stay for arithmetic across cells; the Checks screen says so |
| Compliance rules | stay; the interview may propose one |
| Programme rules, config notes, learned rules | untouched |

## Decisions (2026-09-19)

| Question | Decision |
| --- | --- |
| Where the interview lives | **A new Meaning screen**, with a scope picker (Global or a programme). |
| Global and programme meaning at run time | **Global plus the programme's**; an entry with the same key overrides the global one. |
| A proposal the model cannot place | **Stays open with the model's question** until the administrator places it, marks it "not in the config" (a compliance rule) or "explanation only". |
| A confirmed mapping | **Compiles to a shadow check automatically**, like a guide entry; may also propose a compliance rule, also shadow. |
| Bulk deletes | **One typed word per batch.** |

## Scope · 🟡 in progress

### Part A — edit, delete, bulk, small UI asks · ✅ complete

- [x] Every admin delete requires `?confirm=delete` (API-enforced); bulk delete for
      compliance rules, checks, named values, aliases; a bulk state action on the Rules
      screen; compliance rules editable with a version; checks editable from the list.
- [x] `confirm-delete` and `bulk-bar` components; the Rules screen links to the owning
      screen; the Checks screen points to the report guide for cell-level meaning.
- [x] Delivery programmes: a tinted, bordered card per programme with the code as a chip.
- [x] User console tab title is "Greenlight AI"; `confirm-dialog` ready for the first
      user-side delete. ADR-032; `standards/frontend.md`; training documents.

### Part B — Meaning · ⬜ not started

- [ ] `artifact_samples.scope_code`; three samples per type **per programme**.
- [ ] `meaning_entries`: requirement and cell entries, global or per programme, with
      status (proposed · open · confirmed · rejected), the model's question and the
      administrator's note; today's guide entries migrated as cell entries.
- [ ] The mapping interview: one cached call per OSL section (`admin_map_requirement`)
      proposing requirement → config block → report cells → what to validate, with a
      question when unsure; the model proposes and never compares.
- [ ] Confirm compiles a placed entry into named values and a shadow check scoped to
      the programme; a confirmed compliance suggestion into a shadow compliance rule.
- [ ] Run time: global entries plus the run's programme's, same key overrides, rendered
      to stages 4 and 8 as today's guides are.
- [ ] The Meaning screen: scope picker, samples in scope, Map, rows with pickers from
      the parsed samples, the question in an amber note, confirm / reject / bulk.
- [ ] ADR-033, glossary, training documents, this phase closed out.

## Acceptance criteria · 🟡 in progress

1. [x] A delete without the typed word is refused by the API; a batch of rows goes
   under one word; a compliance rule can be edited and its version increments.
2. [ ] An OSL sample scoped to Account Solicitation and a global one coexist; Map on
   the programme proposes rows from the scoped sample.
3. [ ] Confirming a placed row yields a shadow check with scope `programme:CODE`; an
   unplaced row stays open with the model's question and compiles nothing.
4. [ ] A run of that programme shows the model global plus programme entries, with a
   same-key programme entry replacing the global one.

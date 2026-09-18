# Session Log

Working journal. **Read the "Resume here" block first at the start of every session; update
it and append an entry at the end.** Required fields per entry: branch, phase, status,
what was completed, what's pending, blockers, next concrete action. No PII, no customer
names, no sample data.

---

## Resume here

| Field | Value |
| --- | --- |
| Current phase | **0 — Repo setup** |
| Current milestone | Phase 0 deliverable complete on the branch; PR open |
| Branch | `claude/funny-cerf-jsyvpe` → PR "Phase 0: repo setup" against `main` |
| Last updated | 2026-09-18 |

**Next action:** wait for the human to review and merge the Phase 0 PR. After the merge
the human creates `dev` from `main`. Then start **Phase 1 (UI mock)**: read
`docs/phase-1.md` and `docs/design.md` "UI and report", copy the theme tokens from
`compare-file/ui2` (`config/theme.json`, `app/globals.css`) into `ui-mock/styles.css`, and
build the user-ui pages first. Do not start Phase 2 before the mock walkthrough is done.

**Blocked on the user:** the open questions in `docs/phase-plan.md` (real sample set,
in-house model / serving stack, data dictionary, retention window, finalize gate).

---

## Session: 2026-09-18 (Phase 0 — repo setup)

**Branch:** `claude/funny-cerf-jsyvpe` · **Phase:** 0 · **Status:** deliverable complete,
PR opened.

### What was completed

- Studied `compare-file` (layout, CLAUDE.md, `standards/`, `docs/` phase + ADR + session
  log conventions, `ui-mock/`, `ui2` toolchain, pyproject) and `snopfamily` (CLAUDE.md
  router style, `AI_CONTEXT/` set, GIT_RULES, PR template, CI).
- Agreed with the user: branching main/dev/feature; CI manual-only; Python 3.10 floor +
  pin; ui2 stack + Vitest; compare-file docs layout + "Resume here" + glossary;
  `src/vigilai/` layout; `docker/` dir + root compose; one phase doc per design phase.
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

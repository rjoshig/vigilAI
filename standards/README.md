# Coding Standards

This directory is the **canonical source of truth** for how code is written in this
repository. `CLAUDE.md` keeps a short summary and links here; if the two ever disagree,
this directory wins. Format and most rules come from `compare-file/standards/`.

| Doc | Scope |
| --- | --- |
| [`python.md`](./python.md) | The pipeline, worker, CLI, and FastAPI backend (`src/vigilai/`) and `tests/` |
| [`frontend.md`](./frontend.md) | The two Next.js apps (`user-ui/`, `admin-ui/`) and the static `ui-mock/` |
| [`git.md`](./git.md) | Branching, commits, PRs, pre-push checklist, and the session workflow |

## Source of truth

- **These docs are canonical.** Update the doc here first, then adjust the `CLAUDE.md`
  summary if needed.
- **Standards say _what_ and _how_. ADRs say _why_.** Rationale goes in
  [`../docs/decisions.md`](../docs/decisions.md) as a new ADR entry. When a standard exists
  because of a decision, link the ADR.
- **The product design is `docs/design.md`.** Standards never override it; a conflict
  between the two is an ADR + a question to the user.
- **The phase workflow is unchanged.** Read [`../docs/session-log.md`](../docs/session-log.md)
  at the start of every session and append at the end; phases stay sequential
  ([`../docs/phase-plan.md`](../docs/phase-plan.md)).

## Adoption policy

This repo is new. **All code must comply from the first commit**; there is no legacy to
bring into line. Standalone refactor PRs still need a reason recorded as an ADR.

## The "done" checklist (applies to every task)

1. Code is written, typed, and documented.
2. Tests exist and pass, on synthetic fixtures only, with `LLM_PROVIDER=mock`.
3. Linters / formatters / type-checkers are clean (see the per-language docs).
4. The relevant phase doc is updated (task checked off).
5. `docs/session-log.md` reflects the new state, including the "Resume here" block.
6. Commit is pushed (see [`git.md`](./git.md)).

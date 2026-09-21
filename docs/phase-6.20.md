# Phase 6.20 — Three roles, and a console that shows you only your own job

**Status:** ✅ **complete** — 2026-09-21. Specified and built the same day, in the order
below: the capability table, roles on an account, **the API enforcing them**, then the
consoles, then assigning roles, then dropping the column the list replaced. The
enforcement came before the hiding, deliberately, because a hidden link is not a closed
door.

## Why

There are two roles today — `admin` and `user` — and no matrix. `role == "admin"` is
written out in five routers, and the model's own comment says *"two roles, no permission
matrix"*. That is workable for two roles and stops being workable at three, because the
question stops being *who are you* and becomes *what may you do*.

Two things are wrong in the product as it stands:

1. **The user app shows everybody the admin console.** The sidebar's *Admin console*
   link is unconditional. Somebody who cannot change anything there is still invited in,
   which is confusing at best and, once the console holds settings that decide what
   reaches a model, worse than confusing.
2. **There is no role for the person the training loop was built for.** Phase 6.1
   onwards assumes a senior associate who knows a programme well enough to approve what
   the tool learned from it. That person is not an administrator — they should not be
   creating accounts or editing what the tool is allowed to send to a model — and
   making them one is the only option the product offers.

## The one thing to understand before building any of this

**Login ships off** (ADR-022), and with it off there is exactly one user: a seeded
placeholder, currently *John Doe*, whom `deps.py` hands `is_admin=True`:

```python
is_admin=not settings.admin_auth,   # with the switch off nothing is gated by role
```

So **none of this phase has any effect until `GREENLIGHT_AI_ADMIN_AUTH` and
`GREENLIGHT_AI_USER_AUTH` are on.** With login off, every visitor is the placeholder and
the placeholder can do everything — and that must stay true, because it is what ADR-022
promises: with both switches off the behaviour is exactly as it was before login existed.

This is not a reason to skip the work. It is a reason to **build the enforcement first
and the hiding second**, and never to mistake a hidden link for a closed door. It also
means the acceptance criteria below have to be tested with login *on*, which no existing
UI test does.

**The placeholder holds `user` and `admin`**, so a deployment that has never switched
login on behaves exactly as it does today.

## The roles

Three, and the line between them is **judging the work** versus **defining the
deployment**. A reviewer decides whether a rule is right. An administrator decides what a
programme is, who has an account, and what the tool may send to a model. Different jobs,
different blast radius, and the second group is much smaller.

| Role | What it is for |
| --- | --- |
| **user** | Submits runs and reviews findings in the user app. No admin console at all. |
| **reviewer** | Everything in the console that is about judging the work: approving what the tool learned, the rule surfaces, worked examples, the figures, and the reference data a delivery's vocabulary needs. |
| **admin** | All of that, plus what defines the deployment: programmes, artifact types, meaning, accounts, settings, privacy. |

**A person holds several roles**, and capabilities are the union — holding more roles
never takes anything away. A senior associate is a `user` *and* a `reviewer`; an
administrator is nearly always a `user` too.

## The capability matrix

Roles grant capabilities; **code asks about capabilities, never about roles**. No router
asks whether somebody is a reviewer — it asks whether they may approve training. Adding a
fourth role is then an edit to one table rather than a search through five routers.

| Console screen | Capability | admin | reviewer | user |
| --- | --- | :---: | :---: | :---: |
| Dashboard, **Usage**, **Review load** | `VIEW_ADMIN` | ✅ | ✅ | — |
| **Training** queue — approve, reject, withdraw | `APPROVE_TRAINING` | ✅ | ✅ | — |
| **Checks**, **Compliance rules**, **Rules** | `MANAGE_RULES` | ✅ | ✅ | — |
| **Tell the tool**, **Examples** | `TEACH_MODEL` | ✅ | ✅ | — |
| **Reference data** — aliases, field labels | `MANAGE_REFERENCE` | ✅ | ✅ | — |
| **Reference data** — masked columns | `MANAGE_PRIVACY` | ✅ | — | — |
| **Artifact types** | `MANAGE_ARTIFACTS` | ✅ | — | — |
| **Delivery programmes** | `MANAGE_PROGRAMMES` | ✅ | — | — |
| **Meaning** | `MANAGE_MEANING` | ✅ | — | — |
| **Users** | `MANAGE_USERS` | ✅ | — | — |
| **Settings** | `MANAGE_SETTINGS` | ✅ | — | — |

### Two judgement calls in that table, stated so they can be overruled

**Masked columns are admin-only, even though the rest of Reference data is not.** Naming
a column there is what keeps personal data out of every prompt (ADR-003). It is the
strongest control in the product and the one whose failure is least visible — nothing
goes wrong on screen when a column stops being masked. Aliases and field labels only help
the tool recognise a customer's vocabulary, so they carry none of that risk and stay with
the reviewer. If you disagree, it is one line in `_REVIEWER`.

**Reviewers get the rule surfaces, not just the training queue.** Approving an
observation produces a rule, and a rule that cannot then be activated by the person who
approved it makes the reviewer role a half-job that always needs an administrator. The
shadow-then-activate gate (ADR-021) is what makes this safe: nothing a reviewer activates
starts producing findings without having run silently first.

## The work, in the order worth doing it

### 6.20a — The capability table · ✅ complete

- [x] `src/greenlight_ai/auth/roles.py`: `Role`, `Capability`, the grants, and
      `normalize_roles` / `capabilities_of` / `has_capability` / `describe`.
- [x] `tests/auth/test_roles.py` — eighteen checks, one per line of the matrix above,
      written out rather than derived so changing a grant has to be done deliberately in
      two places.
- [x] Roles add up and never subtract; an account with nothing ticked is still a `user`
      rather than locked out of everything; an unknown stored name is dropped rather
      than trusted.

**Nothing consumes this yet.** It is deliberately a leaf: pure, typed, no imports from
the rest of the package, so the wiring below can be done in any order without a rewrite.

### 6.20b — Several roles on an account · ✅ complete

The storage and the reporting landed early, because the placeholder needed both roles
before the gating arrives — an account that behaves as an administrator while its row
says `user` is a disagreement waiting to lock somebody out.

- [x] `User.roles` as a JSON list beside the single `role`, which **stays until 6.20f**
      holding the strongest role held, so code that still asks `role == "admin"` keeps
      giving the right answer. Added NOT NULL with a server default, so a migrated
      schema matches what `create_all` builds (`c9e1f3a5b7d0`).
- [x] Every existing account keeps exactly what it had, as a list of one. Nothing is
      granted a role it did not have.
- [x] **The placeholder holds `user` and `admin`.** While login is off it is the only
      account there is and `deps.py` already hands it `is_admin=True`, so the stored
      roles now say what the behaviour already is. Seeded that way for a new deployment
      and migrated that way for an existing one.
- [x] `CurrentUser` carries `roles`, and the placeholder branch reports the row's own
      role instead of the literal `"user"` it used to return while behaving as an
      administrator.
- [x] `GET /auth/me` returns `roles`, so neither console has to infer them.
- [x] `accounts.py` no longer asks SQL *is there an administrator?*. JSON membership is
      not portable across SQLite and Postgres (ADR-017), so `_real_admins` and
      `other_active_admins` read the list in Python over what is the smallest table in
      the schema. `users.py` counts the last active administrator the same way.
- [x] `CurrentUser` resolves `capabilities`, and the routers consult those rather than
      `is_admin`. With admin login off the placeholder still holds every capability,
      which is what ADR-022 promises; with it on, an unauthenticated caller on an open
      path is granted nothing rather than inheriting the placeholder's roles.

### 6.20c — The API enforces it · ✅ complete

**This is the part that matters.** Hiding a link is not access control, and anything done
in the UI first is a door that looks shut.

- [x] `require_capability(Capability.X)` builds a guard per capability, and
      `require_admin` is now that guard for `VIEW_ADMIN`. `assert_capability` refuses
      from inside a handler for the two routes whose capability depends on a path
      parameter.
- [x] Each router gets the capability its endpoints actually need: `settings.py` →
      `MANAGE_SETTINGS`, `users.py` → `MANAGE_USERS`, `meaning.py` → `MANAGE_MEANING`.
      `training.py` splits: the observation queue and the candidates to
      `APPROVE_TRAINING`, the rule surfaces to `MANAGE_RULES`, the front door to
      `TEACH_MODEL`. `admin.py` is per endpoint — forty of them — with the bulk delete
      and a definition revert reading their parameter first.
- [x] Twenty-five in-body `require_admin(user)` re-checks went with it. Each sat in an
      endpoint whose own guard is now stricter, so they said something weaker than the
      truth.
- [x] `tests/api/test_capabilities.py`: every capability from an administrator's side, a
      reviewer's and a plain user's, **with both login switches on** — new scaffolding
      rather than a new assertion on old scaffolding.
- [x] 403 rather than 404, and the refusal names what was missing: the screen exists and
      is not theirs, and a bare refusal makes a support conversation impossible.
- [x] **One deliberate exception, recorded in ADR-049.** `GET /admin/scopes` stays on the
      console floor: four screens a reviewer works on scope what they are editing to a
      delivery programme, so all four fetch the list. Reading it is not *managing
      programmes*; writing one is, and that is refused.

### 6.20d — The consoles show each person their own job · ✅ complete

- [x] `GET /auth/me` returns `roles` and `capabilities`, so neither app has to know the
      matrix. A console that recomputed it would disagree with the API the first time a
      grant moved, and would disagree by offering a screen that then refuses.
- [x] **user-ui:** the *Admin console* link renders only with `VIEW_ADMIN`. This is the
      thing that prompted the phase. Two cases are still shown it deliberately: login
      off, and admin login on while this app's is off — there the app does not know who
      is looking, and a link to a console that asks for its own sign-in beats no link.
- [x] **admin-ui:** one table carries each screen's capability and is read twice, for the
      rail and for what a typed URL may render. A screen that is not this person's says
      *"This screen is for administrators"* rather than rendering empty, because an empty
      screen reads as a bug and generates a support call. Somebody with valid credentials
      but no console at all is told once instead of meeting an empty rail.
- [x] Reference data shows aliases and field labels to a reviewer and drops the
      masked-column card, which is not even fetched without the capability, rather than
      hiding the whole screen — that would take a reviewer's own work away to protect one
      card on it.

### 6.20e — Assigning roles · ✅ complete

- [x] The Users screen offers the three roles as checkboxes, with each one's sentence
      from `GET /admin/users/roles` beside it — `describe()`, fetched rather than
      hard-coded, so the console cannot describe a role in words the matrix does not
      support. Not a dropdown: they are not exclusive and a dropdown would say they are.
- [x] Nothing ticked still leaves a plain `user`. Saving an empty form is a mistake, not
      a way to lock somebody out of everything.
- [x] **An administrator cannot remove their own last `admin` role**, and the last
      administrator cannot be demoted or deactivated. Unrecoverable without a database
      edit, so it is a 409 rather than a warning, and the screen shows the API's wording
      so it says which of the two ways it was about to happen.
- [x] Every change is attributed and audited like the rest of the product (ADR-022),
      from what to what. The placeholder's roles are refused: they are what makes the
      product behave as it did before login existed.

### 6.20f — Removing the old field · ✅ complete

- [x] Dropped in its own commit, once nothing read it. `d2f4a6b8c0e1` removes it inside
      `batch_alter_table`, which is how a column goes portably: older SQLite has no
      DROP COLUMN and alembic rebuilds the table (ADR-017). The downgrade puts it back
      and refills it from the list, so a rollback lands on a schema the previous revision
      can work with; both directions were run before the commit.
- [x] `CurrentUser`, `WhoAmIOut` and `UserOut` lose `role`; the Users screen and the
      usage export show every role held. `tests/db/test_migration_chain.py` compares a
      migrated database with the models column for column, so the drop had to land in
      both.

## Acceptance criteria · ✅ complete

- [x] With **login off**, behaviour is what it was: one placeholder who can do
      everything, the admin link visible, nothing gated (ADR-022). Asserted per
      capability, and the 1,672-test suite was green before and after each commit.
- [x] With **login on**, a `user` gets no admin link, is told once if they sign in to the
      console anyway, and is refused every admin route.
- [x] With **login on**, a `reviewer` reaches the training queue, the rule surfaces, the
      worked examples, the figures and the reference data; and is refused programmes,
      artifact types, meaning, users, settings and masked columns.
- [x] A person holding `user` and `reviewer` has exactly a reviewer's capabilities.
- [x] The last administrator cannot be demoted or deactivated, by either route.
- [x] `docs/admin-training.md` has *Who may do what: the three roles*, and
      `docs/user-training.md` has *Why the Admin console link may not be there*. Both are
      in their app's Guide (6.19b), so they are read where the question comes up.
- [x] ADR-049 records the capability model and now three judgement calls: masked columns
      on the admin side, reviewers getting the rule surfaces, and the programme list
      staying on the console floor.

## What this phase deliberately does not do

**No per-object permissions**, no "reviewer for programme AM only". Scope already means
something specific in this product (ADR-029) and overloading it with authorisation would
make both harder to reason about. If a customer needs it, it is its own phase.

**No permission editing in the console.** The matrix is code, reviewed and tested. A
console that lets somebody grant themselves `MANAGE_SETTINGS` is a console with one
role in it.

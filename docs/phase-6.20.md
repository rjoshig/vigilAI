# Phase 6.20 — Three roles, and a console that shows you only your own job

**Status:** 🟡 **in progress** — specified 2026-09-21. **6.20a is built** (the capability
table and its tests) and **6.20b is mostly built** (several roles stored per account, and
the placeholder holding `user` and `admin`). Nothing is enforced yet: no router and
neither console consults a capability. Written as a hand-off: the
thinking that needed doing is done and written down, and the wiring is listed in the
order it is worth doing.

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

### 6.20b — Several roles on an account · 🟡 in progress

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
- [ ] `accounts.py` queries `User.role == "admin"` in SQL to answer *is there an
      administrator?*. JSON membership is not portable across SQLite and Postgres
      (ADR-017), so that check moves into Python over what is a very small table. It
      still reads the legacy field, which is correct until 6.20f.
- [ ] `CurrentUser` resolves `capabilities` and the routers stop consulting `is_admin`.

### 6.20c — The API enforces it · ⬜ not started

**This is the part that matters.** Hiding a link is not access control, and anything done
in the UI first is a door that looks shut.

- [ ] `require_capability(Capability.X)` beside the existing `require_admin`, which
      becomes `require_capability(VIEW_ADMIN)`.
- [ ] Each router gets the capability its endpoints actually need:
      `settings.py` → `MANAGE_SETTINGS`, `users.py` → `MANAGE_USERS`, `meaning.py` →
      `MANAGE_MEANING`, `training.py` → `APPROVE_TRAINING`. `admin.py` is mixed and needs
      it per endpoint — artifacts and programmes to their own capabilities, usage and the
      keyword queue to `VIEW_ADMIN`, the masked-column routes to `MANAGE_PRIVACY`.
- [ ] A test per capability that a reviewer's session is refused a 403 and an
      administrator's is not, **with login on**. No existing test runs with the switches
      on, so this is new scaffolding rather than a new assertion on old scaffolding.
- [ ] 403 rather than 404: the screen exists and is not theirs, and pretending otherwise
      makes support conversations impossible.

### 6.20d — The consoles show each person their own job · ⬜ not started

- [ ] `GET /auth/me` returns `roles` and `capabilities`, so neither app has to know the
      matrix. The matrix lives in one place and the apps read it.
- [ ] **user-ui:** the *Admin console* link renders only with `VIEW_ADMIN`. This is the
      thing that prompted the phase.
- [ ] **admin-ui:** every nav item is gated on its capability, and a screen reached by
      URL without it shows *"This screen is for administrators"* rather than a broken
      page or an empty one. An empty screen reads as a bug and generates a support call.
- [ ] Reference data shows aliases and field labels to a reviewer and hides the
      masked-column card, rather than hiding the whole screen.

### 6.20e — Assigning roles · ⬜ not started

- [ ] The Users screen offers the three roles as checkboxes with `describe()` beside
      each, not a dropdown: they are not exclusive and a dropdown would say they are.
- [ ] **An administrator cannot remove their own last `admin` role**, and the last
      administrator in the deployment cannot be demoted or deactivated. Locking everybody
      out of the console is unrecoverable without a database edit.
- [ ] Every change is attributed and audited like the rest of the product (ADR-022).

### 6.20f — Removing the old field · ⬜ not started

- [ ] Drop `User.role` once nothing reads it, in its own commit, after 6.20b–e have
      been running.

## Acceptance criteria · ⬜ not started

- [ ] With **login off**, behaviour is byte-for-byte what it is today: one placeholder
      who can do everything, the admin link visible, nothing gated (ADR-022).
- [ ] With **login on**, a `user` gets no admin link and a 403 from every admin route.
- [ ] With **login on**, a `reviewer` can approve a training observation, activate the
      rule it became, and edit an attribute alias; and is refused programmes, artifact
      types, meaning, users, settings and masked columns.
- [ ] A person holding `user` and `reviewer` has exactly a reviewer's capabilities.
- [ ] The last administrator cannot be demoted or deactivated.
- [ ] `docs/admin-training.md` gains a section on what each role may do, and
      `docs/user-training.md` says why the admin link may not be there.
- [ ] An ADR records the capability model and the two judgement calls above.

## What this phase deliberately does not do

**No per-object permissions**, no "reviewer for programme AM only". Scope already means
something specific in this product (ADR-029) and overloading it with authorisation would
make both harder to reason about. If a customer needs it, it is its own phase.

**No permission editing in the console.** The matrix is code, reviewed and tested. A
console that lets somebody grant themselves `MANAGE_SETTINGS` is a console with one
role in it.

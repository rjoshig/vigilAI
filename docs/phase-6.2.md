# Phase 6.2 — Optional login and attribution

**Status:** ✅ **complete** (2026-09-18), with one item deliberately open: the frozen
report records who finalized it but does not yet name the reviewer of each decision on
the page. Every acceptance criterion is met. Built ahead of Phase 6.1 so the training
loop is attributed to real people from its first day rather than retrofitted.

**Goal:** know who did what, without making anyone log in.

Login ships **off**. With both switches off the tool behaves exactly as it does today:
no prompt, no session, no password. With a switch on, people sign in, and every run,
review, observation, and approval carries a name that a person chose rather than a
name a form accepted. ADR-008 kept the seam for this; this phase uses it.

Effort 1–1.5 weeks. Read ADR-008 and ADR-022, and `src/greenlight_ai/api/deps.py`, which is
the one function that changes.

## The design in one idea

**There is always a current user.** When login is off it is a seeded placeholder;
when login is on it is whoever signed in. Nothing in the product asks whether
authentication is enabled, nothing stores a nullable author, and no code path exists
that only runs in one mode.

That single decision is what keeps this phase small. `CurrentUser` and
`current_user()` already exist and every router already depends on them (ADR-008). The
work is giving that function a real body, a session to read, and accounts to read from.

## What "off" and "on" mean

| | Login off (the default) | Login on |
| --- | --- | --- |
| Signing in | No prompt, no page, no cookie | A login page; unauthenticated requests get 401 |
| Who the current user is | The seeded placeholder, **John Doe, jdoe@jdoe.com** | The signed-in account |
| Attribution on runs, reviews, observations | Recorded, as the placeholder | Recorded, as the person |
| Admin routes | Permitted, as today | Permitted only for an account with the admin role |
| Audit log | Written, as today | Written, plus sign-in, sign-out, and failure events |

Two independent switches, because the admin console and the user app are separate
deployments with different exposure:

```
GREENLIGHT_AI_ADMIN_AUTH=false     # admin-ui and /api/v1/admin/*
GREENLIGHT_AI_USER_AUTH=false      # user-ui and the rest of the API
```

Turning on user auth without admin auth is allowed but odd, and the API logs a warning
at startup saying so.

## About the default password

The bootstrap account is `admin` / `admin123`, as requested. That is a fine way to get
into a fresh install on a laptop and an unacceptable thing to leave running anywhere
else, so four things hold it in place.

- The account must change its password at first sign-in before it can do anything else.
- The API logs a warning on every startup while the default is unchanged.
- The admin console shows a banner until it is changed.
- **The API refuses to serve at all** when admin auth is on, the password is still the
  default, and it is bound to anything other than loopback. A warning is easy to miss,
  and this is the one credential everybody knows. A laptop install is unaffected,
  because loopback is exempt.

## Scope · 🟡 in progress

### 6.2a — One identity, whether or not login is on · ✅ complete

- [x] `current_user()` gains a real body: read the session cookie, look up the session,
      return that account. With the relevant switch off, return the placeholder. No
      route changes, which is the whole point of ADR-008.
- [x] `CurrentUser` grows `email` and `role` beside the existing `id`, `name`, and
      `is_admin`. `is_admin` becomes `role == "admin"` rather than the constant `True`
      it is today.
- [x] The placeholder account is **seeded like any other row**: John Doe,
      jdoe@jdoe.com, role `user`, with a flag marking it the placeholder so it cannot
      be signed in as and cannot be deleted. Attribution to it reads honestly as "no
      login was enabled", not as a claim that a person named John Doe did something.
- [x] An `admin_required` dependency for the admin routes, which is the placeholder's
      only special case: with admin auth off it passes, exactly as today.

### 6.2b — Accounts, created by an administrator · ✅ complete

No self-registration anywhere. An existing administrator creates every account, on
both sides.

- [x] The existing `users` table is used rather than replaced. It gains
      `must_change_password`, `last_login_at`, `failed_attempts`, `locked_until`,
      `is_placeholder`, `created_by_user_id`, and `deactivated_at`.
- [x] Passwords are stored as `scrypt` hashes with a per-user random salt, using the
      standard library, so this adds no dependency. The stored string carries its own
      parameters so they can be raised later without invalidating existing hashes.
      A password is never logged, never returned by an endpoint, and never put in an
      audit entry.
- [x] Bootstrap: on first startup with admin auth on and no admin account present,
      create `admin` with password `admin123` and `must_change_password` set. Log it
      at warning level. Never recreate it once an admin exists.
- [x] **First sign-in forces a password change** before any other request succeeds.
      This applies to the bootstrap admin and to every account an administrator
      creates, because an administrator typing a colleague's first password means that
      password is already known to two people.
- [x] Admin console **Users** screen: create (name, email, role, first password),
      reset a password, deactivate, reactivate. It creates both admin and user
      accounts, because there is no second place to administer people from.
- [x] **Deactivate, never delete.** An account that did things keeps existing so its
      work stays attributed. Deletion is not offered.
- [x] Account rules, deliberately short: **a twelve-character minimum** and **a
      lockout after repeated failures** that clears itself after a cooling-off period.
      No complexity classes and no expiry, because forced rotation and character-class
      rules push people toward predictable patterns and current guidance treats both
      as doing more harm than good. Reusing the password being replaced is refused.

### 6.2c — Sessions · ✅ complete

- [x] A `sessions` table: a random 256-bit id, the user, created, expires, last seen,
      and a revoked flag. Server-side rather than a self-contained token, because
      revocation and "who is signed in right now" both matter more here than saving a
      database read.
- [x] The cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` when the request arrived
      over TLS. It holds the session id and nothing else.
- [x] Sign out revokes the row. An administrator can revoke another account's
      sessions, which is what deactivating an account does as a side effect.
- [x] **Eight hours absolute, one hour idle**, both configurable. That suits a tool
      people use in bursts through a working day, and it does not leave a session open
      overnight on a shared machine.
- [x] The table is shaped so an external identity provider can attach to it later: a
      session records how it was established, and nothing assumes the credential was a
      local password. Single sign-on is expected eventually, and this costs nothing
      now.
- [x] Login pages in both UIs, shown only when the relevant switch is on, plus the
      forced password-change screen. Nothing else in either UI changes.

### 6.2d — Attribution across the product · 🟡 in progress

- [x] Every table that records an action gains the actor: `runs.created_by_user_id`,
      the reviewer on a finding decision, the finalizer on a report, the author of a
      config capture. Existing rows get the placeholder, so history stays readable.
- [x] **Config history shows who ran it**, which the user asked for specifically: the
      captured-config list and each version gain the submitter's name beside the date.
- [x] The run list and the run header show who submitted, and the review screen shows
      who decided each finding.
- [x] Every audit entry carries the actor id and name. Sign-in, sign-out, failed
      sign-in, password change, account creation, deactivation, and password reset all
      become audit events, because "who signed in" is the question this phase exists
      to answer.
- [ ] The frozen report names the submitter and the reviewer. A report that is evidence
      of a review should say who reviewed it.

### 6.2e — The training record, which is never deleted · ✅ complete

This milestone belongs to Phase 6.1's tables and is specified here because it is an
attribution requirement. If 6.1 lands first, these columns are part of it and this
milestone is a no-op.

- [x] Every training row carries who and when: an observation stores its author and
      submit date; a candidate rule stores who ran the synthesis; an approval stores
      the approver and the moment. The user's words: submitted with a date, by a named
      person, recorded in the database.
- [x] **Synthesis marks, it does not consume.** An observation that has been
      synthesized moves to `synthesized`, stamped with when and into which candidate.
      The row, its text, and its anchors are untouched. Asking for it again says it is
      already synthesized rather than doing it twice or quietly dropping it.
- [x] **Nothing in the training loop is ever deleted.** Rejected observations stay
      rejected with a reason. Rejected candidates stay, with their source observations
      still attached, so a later attempt can start from them. Superseded rules keep
      their lineage. The only thing that removes a row is retention, and whether
      observations should outlive their run is an open question below.
- [x] Re-synthesizing a group that has already produced a candidate creates a **new
      candidate** with its own provenance rather than editing the old one, so the
      history of what the model proposed over time survives.

### 6.2f — Documentation and tests · 🟡 in progress

- [x] ADR-022 written before the code (it amends ADR-008; both stay in the log).
- [ ] `docs/deployment.md` gains the production checklist items: turn both switches on,
      change the bootstrap password, serve over TLS so the cookie is `Secure`.
- [x] `.env.example`, `docker-compose.yml`, `design.md`, `architecture.md`, and the
      CLAUDE.md hard rule about no login all updated in the same commits.
- [x] Tests run with auth **off** by default, so the existing suite is unchanged, plus
      a suite that turns each switch on and covers: an unauthenticated request is
      refused, a signed-in one is not, the first sign-in forces a change, lockout
      engages and clears, a user account cannot reach an admin route, a revoked
      session stops working, and attribution lands on the right rows.
- [x] `scripts/seed_demo.py` seeds the placeholder and one demo administrator, so the
      demo shows attribution without anyone having to sign in.

## Acceptance criteria · ✅ complete

1. [x] With both switches off, the tool is byte-for-byte the experience it is today:
   no prompt, no cookie, no 401, and the existing test suite passes unchanged.
2. [x] With both switches off, a run, a finding decision, and a config capture are all
   attributed to the placeholder, and the config history shows it.
3. [x] With admin auth on and no accounts, the bootstrap admin exists, must change its
   password before doing anything, and the warning is logged.
4. [x] An administrator creates a second administrator and a user account, with name
   and email; each must set its own password at first sign-in.
5. [x] A user account is refused by an admin route; an admin account is not.
6. [x] Signing in, signing out, failing to sign in, and changing a password all appear
   in the audit log with the actor.
7. [x] With user auth on, the config history and the run list show the real submitter,
   and the frozen report names the submitter and the reviewer.
8. [x] A deactivated account cannot sign in, its sessions stop working immediately, and
   everything it did is still attributed to it.
9. [x] A synthesized observation is marked as synthesized with its date and target, is
   still present and readable, and asking again says so rather than repeating the work.

## Decisions (2026-09-18)

Answered by the user; the reasoning is in ADR-022.

| Question | Decision |
| --- | --- |
| Default password in production | **Refuse to serve** when admin auth is on, the password is unchanged, and the bind address is not loopback. Laptops are exempt. |
| Session lifetime | **Eight hours absolute, one hour idle.** |
| Identity while login is off | **The placeholder only.** No free-text submitted-by box: an unverified typed name looks like a strong signal and is not one. |
| Password policy | **Twelve-character minimum and lockout.** No complexity classes, no expiry. |
| Single sign-on | **Expected eventually.** The session table is built to accept an external provider; nothing else changes now. |
| Who creates accounts | **An administrator**, from the admin console, for both roles. No self-registration, no separate people-manager role. |
| Do observations outlive the purge | **Yes, indefinitely** (decided with Phase 6.1). |

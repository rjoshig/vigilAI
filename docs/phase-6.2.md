# Phase 6.2 — Optional login and attribution

**Status:** ⬜ **not started** — specified 2026-09-18 at the user's request, to be
scheduled. Depends on nothing; it can be built before, during, or after Phase 6.1,
though the two meet in 6.2e and building 6.1 first makes that milestone concrete
rather than speculative.

**Goal:** know who did what, without making anyone log in.

Login ships **off**. With both switches off the tool behaves exactly as it does today:
no prompt, no session, no password. With a switch on, people sign in, and every run,
review, observation, and approval carries a name that a person chose rather than a
name a form accepted. ADR-008 kept the seam for this; this phase uses it.

Effort 1–1.5 weeks. Read ADR-008 and ADR-022, and `src/vigilai/api/deps.py`, which is
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
VIGILAI_ADMIN_AUTH=false     # admin-ui and /api/v1/admin/*
VIGILAI_USER_AUTH=false      # user-ui and the rest of the API
```

Turning on user auth without admin auth is allowed but odd, and the API logs a warning
at startup saying so.

## About the default password

The bootstrap account is `admin` / `admin123`, as requested. That is a fine way to get
into a fresh install on a laptop and an unacceptable thing to leave running anywhere
else, so three things hold it in place: the account must change its password at first
sign-in before it can do anything else, the API logs a warning on every startup while
the default is unchanged, and the admin console shows a banner until it is. Whether a
production deployment should refuse to serve at all while the default stands is an
open question below; the recommendation is that it should.

## Scope · ⬜ not started

### 6.2a — One identity, whether or not login is on · ⬜ not started

- [ ] `current_user()` gains a real body: read the session cookie, look up the session,
      return that account. With the relevant switch off, return the placeholder. No
      route changes, which is the whole point of ADR-008.
- [ ] `CurrentUser` grows `email` and `role` beside the existing `id`, `name`, and
      `is_admin`. `is_admin` becomes `role == "admin"` rather than the constant `True`
      it is today.
- [ ] The placeholder account is **seeded like any other row**: John Doe,
      jdoe@jdoe.com, role `user`, with a flag marking it the placeholder so it cannot
      be signed in as and cannot be deleted. Attribution to it reads honestly as "no
      login was enabled", not as a claim that a person named John Doe did something.
- [ ] An `admin_required` dependency for the admin routes, which is the placeholder's
      only special case: with admin auth off it passes, exactly as today.

### 6.2b — Accounts, created by an administrator · ⬜ not started

No self-registration anywhere. An existing administrator creates every account, on
both sides.

- [ ] The existing `users` table is used rather than replaced. It gains
      `must_change_password`, `last_login_at`, `failed_attempts`, `locked_until`,
      `is_placeholder`, `created_by_user_id`, and `deactivated_at`.
- [ ] Passwords are stored as `scrypt` hashes with a per-user random salt, using the
      standard library, so this adds no dependency. The stored string carries its own
      parameters so they can be raised later without invalidating existing hashes.
      A password is never logged, never returned by an endpoint, and never put in an
      audit entry.
- [ ] Bootstrap: on first startup with admin auth on and no admin account present,
      create `admin` with password `admin123` and `must_change_password` set. Log it
      at warning level. Never recreate it once an admin exists.
- [ ] **First sign-in forces a password change** before any other request succeeds.
      This applies to the bootstrap admin and to every account an administrator
      creates, because an administrator typing a colleague's first password means that
      password is already known to two people.
- [ ] Admin console **Users** screen: create (name, email, role, first password),
      reset a password, deactivate, reactivate. It creates both admin and user
      accounts, because there is no second place to administer people from.
- [ ] **Deactivate, never delete.** An account that did things keeps existing so its
      work stays attributed. Deletion is not offered.
- [ ] Sensible account rules, each of which is one line of code and saves an
      afternoon later: a minimum password length, a lockout after repeated failures
      that clears itself after a cooling-off period, and a refusal to reuse the
      password being replaced.

### 6.2c — Sessions · ⬜ not started

- [ ] A `sessions` table: a random 256-bit id, the user, created, expires, last seen,
      and a revoked flag. Server-side rather than a self-contained token, because
      revocation and "who is signed in right now" both matter more here than saving a
      database read.
- [ ] The cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` when the request arrived
      over TLS. It holds the session id and nothing else.
- [ ] Sign out revokes the row. An administrator can revoke another account's
      sessions, which is what deactivating an account does as a side effect.
- [ ] An absolute lifetime and an idle timeout, both configurable, both with defaults
      that suit an internal tool rather than a bank.
- [ ] Login pages in both UIs, shown only when the relevant switch is on, plus the
      forced password-change screen. Nothing else in either UI changes.

### 6.2d — Attribution across the product · ⬜ not started

- [ ] Every table that records an action gains the actor: `runs.created_by_user_id`,
      the reviewer on a finding decision, the finalizer on a report, the author of a
      config capture. Existing rows get the placeholder, so history stays readable.
- [ ] **Config history shows who ran it**, which the user asked for specifically: the
      captured-config list and each version gain the submitter's name beside the date.
- [ ] The run list and the run header show who submitted, and the review screen shows
      who decided each finding.
- [ ] Every audit entry carries the actor id and name. Sign-in, sign-out, failed
      sign-in, password change, account creation, deactivation, and password reset all
      become audit events, because "who signed in" is the question this phase exists
      to answer.
- [ ] The frozen report names the submitter and the reviewer. A report that is evidence
      of a review should say who reviewed it.

### 6.2e — The training record, which is never deleted · ⬜ not started

This milestone belongs to Phase 6.1's tables and is specified here because it is an
attribution requirement. If 6.1 lands first, these columns are part of it and this
milestone is a no-op.

- [ ] Every training row carries who and when: an observation stores its author and
      submit date; a candidate rule stores who ran the synthesis; an approval stores
      the approver and the moment. The user's words: submitted with a date, by a named
      person, recorded in the database.
- [ ] **Synthesis marks, it does not consume.** An observation that has been
      synthesized moves to `synthesized`, stamped with when and into which candidate.
      The row, its text, and its anchors are untouched. Asking for it again says it is
      already synthesized rather than doing it twice or quietly dropping it.
- [ ] **Nothing in the training loop is ever deleted.** Rejected observations stay
      rejected with a reason. Rejected candidates stay, with their source observations
      still attached, so a later attempt can start from them. Superseded rules keep
      their lineage. The only thing that removes a row is retention, and whether
      observations should outlive their run is an open question below.
- [ ] Re-synthesizing a group that has already produced a candidate creates a **new
      candidate** with its own provenance rather than editing the old one, so the
      history of what the model proposed over time survives.

### 6.2f — Documentation and tests · ⬜ not started

- [ ] ADR-022 written before the code (it amends ADR-008; both stay in the log).
- [ ] `docs/deployment.md` gains the production checklist items: turn both switches on,
      change the bootstrap password, serve over TLS so the cookie is `Secure`.
- [ ] `.env.example`, `docker-compose.yml`, `design.md`, `architecture.md`, and the
      CLAUDE.md hard rule about no login all updated in the same commits.
- [ ] Tests run with auth **off** by default, so the existing suite is unchanged, plus
      a suite that turns each switch on and covers: an unauthenticated request is
      refused, a signed-in one is not, the first sign-in forces a change, lockout
      engages and clears, a user account cannot reach an admin route, a revoked
      session stops working, and attribution lands on the right rows.
- [ ] `scripts/seed_demo.py` seeds the placeholder and one demo administrator, so the
      demo shows attribution without anyone having to sign in.

## Acceptance criteria · ⬜ not started

1. [ ] With both switches off, the tool is byte-for-byte the experience it is today:
   no prompt, no cookie, no 401, and the existing test suite passes unchanged.
2. [ ] With both switches off, a run, a finding decision, and a config capture are all
   attributed to the placeholder, and the config history shows it.
3. [ ] With admin auth on and no accounts, the bootstrap admin exists, must change its
   password before doing anything, and the warning is logged.
4. [ ] An administrator creates a second administrator and a user account, with name
   and email; each must set its own password at first sign-in.
5. [ ] A user account is refused by an admin route; an admin account is not.
6. [ ] Signing in, signing out, failing to sign in, and changing a password all appear
   in the audit log with the actor.
7. [ ] With user auth on, the config history and the run list show the real submitter,
   and the frozen report names the submitter and the reviewer.
8. [ ] A deactivated account cannot sign in, its sessions stop working immediately, and
   everything it did is still attributed to it.
9. [ ] A synthesized observation is marked as synthesized with its date and target, is
   still present and readable, and asking again says so rather than repeating the work.

## Open questions for the user

- [ ] **Should production refuse to start on the default password?** The
      recommendation is yes when admin auth is on and the process is not on loopback.
      A warning is easy to miss, and this is the one credential everybody knows.
- [ ] **Session lifetime and idle timeout.** A working day and an hour idle are a
      reasonable internal default. Longer is friendlier; shorter is safer.
- [ ] **Password rules.** A minimum length is assumed. Expiry, complexity requirements,
      and history are not, because current guidance treats forced rotation as harmful
      more often than helpful. Say if a policy applies here.
- [ ] **Who creates user accounts?** The proposal is that an administrator does, from
      the admin console, for both roles. The alternative is a separate people-manager
      role, which seems like more machinery than this needs.
- [ ] **Should observations outlive their run?** The 90-day purge would take them with
      the run. An observation is institutional knowledge, and the rule it produced
      outlives the run already, so keeping them longer is probably right — but it
      means keeping text a person typed while looking at customer data.
- [ ] **Do you want a real directory later?** Nothing here rules out single sign-on,
      and the session table is where it would attach. Worth knowing whether it is
      coming, because it changes nothing now and quite a lot in a year.

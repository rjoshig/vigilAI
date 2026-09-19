# Phase 6.3 — Runtime settings in the admin console

**Status:** ✅ **complete** (2026-09-18). Specified and built the same day, at the
user's request, during Phase 6.2.

**Goal:** move day-to-day operational control out of `.env` and into the admin
console, without taking `.env` away. An administrator changes the model, the
concurrency, the retention window, or the login switches from a screen, and the change
takes effect in seconds. A deployment that never opens that screen behaves exactly as
it always did.

Read ADR-023 before changing anything here.

## The three layers

**Admin console, then `.env`, then the built-in default.** The table holds overrides
only, so a key nobody has touched still follows the environment. That is the property
that made this safe to add to a system already running.

Two consequences worth stating plainly, because both have bitten other projects:

- **Nothing is read at import time.** A module-level constant is fixed for the life of
  the process, and that is the usual reason a "runtime" setting turns out not to be
  one. Values resolve where they are used: per request in the API, per job in the
  worker.
- **The console shows the layer.** Every value carries a badge saying whether it came
  from the console, from `.env`, or from the default. This is what prevents the hour
  spent wondering why a value differs from the file on disk.

## What the console may not change

| Setting | Why not |
| --- | --- |
| `DATABASE_URL` | The override lives in the database. A value that gates access to its own store cannot live in it. |
| `GREENLIGHT_AI_DATA_DIR` | Changing it at runtime orphans every stored file. |
| `GREENLIGHT_AI_BIND_HOST` | It decides whether the bootstrap-password refusal applies, so it is not something the console may soften. |
| `GREENLIGHT_AI_SECRET_KEY` | It decrypts the secrets in the table. Storing it there protects nothing. |

They appear in the console read-only, with the reason, because "you cannot change this
here" is more useful than not showing it at all.

## Scope · ✅ complete

### 6.3a — Resolution and the registry · ✅ complete

- [x] `config/registry.py`: every setting declared once with its type, bounds,
      default, environment variable, help text, and whether it is runtime-editable.
      The console renders itself from this, so the code and the console cannot
      disagree about what a setting is.
- [x] `config/store.py`: `resolve`, `effective`, `fallback`, `write_setting`,
      `clear_setting`, and a five-second per-process cache that a write invalidates
      immediately. A malformed stored value is reported and ignored rather than
      taking the service down, and a database it cannot read falls back to the last
      known values.
- [x] `app_settings` holds overrides only; `config_changes` is append-only and keeps
      the previous value, which is what makes "put it back" a button.
- [x] Migration `71906528d2aa`, verified up and down on SQLite.

### 6.3b — Secrets · ✅ complete

- [x] `config/secrets.py`: `MultiFernet` from the first day, so rotating the master
      key is adding a key to the front of a list rather than a migration written
      under pressure.
- [x] **Without a master key a secret is refused, not stored.** The environment stays
      the only place it can come from. Refusing is honest; storing it in the clear
      while implying otherwise is not.
- [x] A secret never travels outward. Resolution reports that one is set and its last
      four characters; only the adapter decrypts, and the change log records that it
      changed and never what it was.

### 6.3c — Everything reads through it · ✅ complete

- [x] The adapter: provider, base URL, model, key, token caps, timeout, concurrency,
      tripwire, and prompt logging. The worker resolves them per job, so a provider
      change applies to the next run without a restart.
- [x] Login: both switches, session lifetime, idle timeout, password minimum, and the
      lockout rules, resolved per request.
- [x] Throughput: runs in flight, runs started per window, the window length, the
      longest acceptable queue wait, and the per-order cap that used to be a constant.
- [x] Uploads and retention.

### 6.3d — The endpoints · ✅ complete

- [x] `GET /admin/settings` groups every setting with its effective value, its source,
      and what it would fall back to.
- [x] `POST /admin/settings` and `DELETE /admin/settings/{key}` to set and revert.
- [x] `GET /admin/settings/history`, the change log.
- [x] `POST /admin/settings/test-model` makes one cheap call with the settings as they
      resolve. Answering "did I type the key correctly" beats a run failing at stage
      two.

### 6.3e — The console screen · ✅ complete

- [x] One card per group, each setting with its help text, an input suited to its
      type, and a badge saying which layer supplied the value.
- [x] Revert, shown only on a setting the console has overridden, labelled with what
      it will revert to.
- [x] The secret field: never a value, only "not set" or the last four characters, a
      blank input that keeps the current key, and an explicit clear.
- [x] A connection test in the model section, reporting provider, model, and latency
      or the failure.
- [x] Confirmation on the changes that can hurt: switching admin login off, switching
      it on, and shortening retention.
- [x] The change history at the foot of the page.

### 6.3f — Documentation · ✅ complete

- [x] ADR-023.
- [x] `.env.example` gains a note that these are now defaults the console can
      override, and `deployment.md` gains the master key and its backup.
- [x] `architecture.md` and `design.md` updated.

## Acceptance criteria · ✅ complete

1. [x] A setting nobody has touched resolves from `.env`, and from the built-in
   default when `.env` is silent.
2. [x] A value set in the console wins over `.env`, and reverting it puts the
   environment back.
3. [x] The database URL, the data directory, and the bind address cannot be changed
   through the API, and say why.
4. [x] A secret is refused when no master key is configured, is stored encrypted when
   one is, never appears in any response or log, and survives a key rotation.
5. [x] An out-of-range or malformed value is refused with a readable reason, and a
   malformed value already in the table is ignored rather than fatal.
6. [x] Every change is in the log with its previous value and who made it.
7. [x] Changing the per-order cap or the start-rate limit changes what the next
   submission does, with no restart.
8. [x] An administrator can do all of the above from the console screen.

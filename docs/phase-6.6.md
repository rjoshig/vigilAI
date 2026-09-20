# Phase 6.6 — Themes, previewed one by one and set from the admin console

**Status:** ✅ **complete** (2026-09-19). Numbered 6.6 because 6.5 is the recurring
training-documentation phase. ADR-031 records who decides the theme.

**Goal:** more than two looks, a way to step through them one at a time and pick one,
and an administrator's control over what every user sees.

## Done ahead of the phase (2026-09-19)

The three palettes from `compare-file/ui2` (`default`, `light-blue-yellow`,
`classic-teal`), each with a light and a dark variant, are in both apps, chosen by
`GREENLIGHT_AI_UI_THEME` in `.env` and read at request time so a change shows on the next
page load. That covers 6.6a's palettes and the environment layer of 6.6c; the picker
and the console setting remain.

## What existed before

Both apps shipped **two themes**: light (the default) and dark, switched by the sun/moon
button at the foot of the sidebar and remembered per browser. The colour tokens are
CSS variables on `:root` and `.dark`. The Phase 1 mock carried a **third palette**,
`light-blue-yellow`, in both a light and a dark variant; it was never brought into the
apps and is the first candidate for a named theme here.

## Scope · ✅ complete

### 6.6a — Named themes · ✅ complete

- [x] A theme is a named set of colour tokens, declared in each app's `globals.css`
      and kept identical between them. Shipped: `default`, `light-blue-yellow`, and
      `classic-teal` from compare-file, plus `classic-teal-navy`, the teal page with
      a navy sidebar and a yellow mark, each in light and dark. Adding a theme is one
      block of tokens and one entry in `lib/theme.ts`.
- [x] Every theme must pass the same contrast check for text, badges, and the
      severity colours, because a finding's severity is carried by colour and a theme
      that flattens it is a defect, not a preference. `lib/contrast.test.ts` in each
      app reads `globals.css` and checks every palette in both modes: body text
      4.5:1, brand surfaces 2.5:1 (a floor under the compare-file values), each
      severity 2:1 against the page and severity hues 30° apart.

### 6.6b — Stepping through themes · ✅ complete

- [x] A **theme picker** in the user app's sidebar, in place of the two-way toggle:
      the current theme's name with **previous** and **next** controls, so a person
      can bring up each theme in turn on the real screens and stop on the one they
      want. The choice is remembered per browser, as today.
- [x] The same picker in the admin console.

### 6.6c — The administrator's control · ✅ complete

- [x] Two runtime settings in the console's Settings screen, under a new **Appearance**
      group, resolved like every other setting (console over `.env` over default,
      ADR-023): the **default theme** every user starts on, and **whether users may
      change it**. When they may not, the picker is hidden and the default applies
      everywhere.
- [x] Both apps read both on every page load (server side, from `GET /appearance`,
      falling back to `.env` when the API is silent) and re-read them in open tabs
      every minute and on return to the tab, so a change made in the console shows
      up without a redeploy.
- [x] A user's own choice, where allowed, wins over the default for that browser; the
      default wins the moment the administrator locks it.

### 6.6d — Documentation · ✅ complete

- [x] `user-training.md` (the picker) and `admin-training.md` (the Appearance group)
      updated in the same change, per Phase 6.5.

## Acceptance criteria · ✅ complete

1. [x] Three or more named themes render both apps with every severity colour
   distinguishable.
2. [x] The picker steps through every theme in order and the choice survives a reload.
3. [x] Setting the default theme in the console changes what a new browser sees, and
   locking it hides the picker for every user, with no redeploy.

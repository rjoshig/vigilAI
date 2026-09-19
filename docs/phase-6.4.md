# Phase 6.4 — Showing the mode, and notes that follow a configuration

**Status:** ⬜ **not started** — specified 2026-09-19 at the user's request. Open
questions at the foot of this doc are being answered before the build.

**Goal:** two things a person using the tool cannot see today.

1. **Whether Train AI mode is on.** Today the mode changes what the user app offers,
   but nothing on the screen says the mode exists. A reviewer who sees a "What should
   this check?" button has no way to know it is there because an administrator
   switched something on, or that what they type is being collected.
2. **Standing notes on a configuration.** A reviewer who knows that *this*
   configuration carries special rules has nowhere to write that down once. Today it
   goes in a run's free-text notes and is gone by the next run. The request is a note
   tied to the configuration id that reaches the model on every future run using that
   configuration, and that an administrator sees in the training queue as a
   configuration-specific comment.

Effort about a week. Depends on Phase 6.1 (Train AI mode and the queue) and ADR-020
(guidance as additive prompt context).

## The idea behind each half

**The indicator is a statement of what is being collected.** Under Train AI mode the
tool records what people write. The honest thing is to say so, in the same place the
person is looking, and to mark every control that exists only because the mode is on.
When the mode is off the indicator still shows, grey, so "off" is a visible state and
not an absence.

**A configuration note is guidance, not a rule.** It reaches the model the way scope
standing instructions do (ADR-020): as background, labelled as background, never as a
requirement. It changes what the model pays attention to; it does not make anything
pass or fail. If an administrator wants it to *enforce* something, the note is also an
observation in the queue, and the ordinary loop turns it into a rule a person approves
(ADR-021). One mechanism for context, one for rules, and the note feeds both.

## Scope · ⬜ not started

### 6.4a — The mode indicator · ⬜ not started

- [ ] A small status line under the vigilAI mark in the user app's sidebar: **Train AI
      mode** with a green dot when on and a grey dot when off. Read from
      `GET /training/config`, which already exists, and updated without a reload when
      an administrator flips the switch (the config is re-read on navigation, and the
      five-second settings cache means it lags at most that long).
- [ ] Every control that exists only because the mode is on carries the same mark: the
      "What should this check?" buttons, the observation dialog, the My observations
      page, and the configuration-note field. A short tag, "Train AI", beside each, so
      a person can tell at a glance which parts of the screen are collecting what they
      type.
- [ ] One sentence on hover or beside the indicator saying what the mode does: what
      you write here is recorded and reviewed by an administrator before it changes
      anything.
- [ ] The admin console shows the same indicator in its own sidebar, because an
      administrator reading the queue should see at once whether new observations can
      still arrive.

### 6.4b — Notes that follow a configuration · ⬜ not started

The configuration id is the order's ETL configuration number, the Solution Canvas
config number. The new-run form says so under the field (done 2026-09-19), because a
note that follows a configuration only makes sense to someone who knows what the
field holds.

- [ ] `config_notes`: `configuration_id`, `text`, `author`, `author_user_id`,
      `is_active`, `version`, `created_at`, `updated_at`. Tied to the configuration
      id, so it applies to every version of that configuration and every customer
      that runs it, until someone switches it off.
- [ ] The note is written from two places: the new-run form, beside the configuration
      id, and the config history page, on the configuration's row. Both show any note
      already in force so a person adds to it rather than writing a second one.
- [ ] **The note reaches the model as background on every run that uses the
      configuration**, through the existing guidance preamble (`pipeline/guidance.py`),
      labelled as a configuration note. Empty means nothing is added, which keeps the
      ADR-020 rule that configuring nothing changes nothing.
- [ ] **The note appears in the admin training queue** as a configuration-specific
      comment, with its author and the configuration it belongs to. From there an
      administrator can do what they do with any observation: leave it as guidance,
      or synthesize it into a candidate rule scoped to that configuration.
- [ ] The run page shows the note that was in force when the run was submitted, and
      the frozen report records it, because a reviewer reading a finding needs to
      know what context the model was given.
- [ ] Edits are versioned and the old text kept, for the same reason observations are:
      the record of what someone said is worth more than the row it occupies.
- [ ] Rules scoped to a configuration: the rule scope gains `config:<id>` beside
      `all`, a customer name, and `programme:CODE`, so a rule learned from a
      configuration note applies only to runs of that configuration.

### 6.4c — Documentation and tests · ⬜ not started

- [ ] ADR-024, written before the code: a configuration note is guidance and an
      observation at once, never a rule on its own.
- [ ] `design.md`, `architecture.md`, `glossary.md` (configuration note), and the
      user-ui and admin-ui READMEs.
- [ ] Tests: the preamble carries a note only for runs of that configuration; the note
      appears in the queue; a rule scoped `config:<id>` fires on that configuration and
      no other; the indicator reflects the switch in both states.

## Acceptance criteria · ⬜ not started

1. [ ] With Train AI mode off, the user app shows a grey "Train AI mode off" line
   under the mark, and nothing else about training appears.
2. [ ] With it on, the line turns green, and every training-only control is tagged.
3. [ ] A note written against a configuration reaches the model as background on the
   next run of that configuration and on no other, and the run page shows it.
4. [ ] The note appears in the admin training queue as a configuration-specific
   comment and can be synthesized into a candidate scoped to that configuration.
5. [ ] Switching a note off stops it applying to the next run; the old text is kept.

## Open questions for the user

- [ ] **Does a configuration note need an administrator before it applies?** As
      specified, it applies as background at once and appears in the queue for an
      administrator to turn into a rule if they choose. The alternative is that
      nothing reaches the model until an administrator approves the note. Faster
      versus safer.
- [ ] **Does the note depend on Train AI mode?** It could be available always, since
      it is guidance rather than training; or only when the mode is on, since that is
      the mode under which the tool collects what people write.
- [ ] **Who may write one?** Anyone, as with observations, or only the person who
      submitted a run with that configuration?
- [ ] **Where should the indicator live in the admin console?** The sidebar mirrors
      the user app; the Settings screen already shows the switch itself.

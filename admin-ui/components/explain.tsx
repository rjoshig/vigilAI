"use client";

/**
 * Two things the console has to say about itself (Phase 6.14c, 6.14d).
 *
 * **`<Explain>`** is help: what this surface is for, how it is meant to be used, and
 * what belongs somewhere else. An administrator choosing between sixteen places to
 * write a rule is choosing well only if each one says what it is. Help is a setting
 * (`ui.tooltips`, on by default) because it stops being help once you know the
 * product.
 *
 * **`<FieldEffect>`** is not help, and never hides. It states what a field *does to a
 * run*: whether it reaches the model, whether code evaluates it, or whether it is
 * reference material. An administrator cannot see a prompt, so this marker is the only
 * account they get of where their words end up — and a console that says a field is
 * background when it now decides something is worse than a console that says nothing.
 * `docs/model-context.md` is the register these quote.
 *
 * Both render nothing at all when they have nothing to say, so a field that neither
 * reaches the model nor is compared stays undecorated.
 */

import { BookOpen, Cpu, HelpCircle, NotebookPen, Ruler, Tag, Users } from "lucide-react";
import * as React from "react";

import { usePalette } from "@/components/palette-provider";
import { cn } from "@/lib/utils";

/**
 * What a field does to a run — who or what actually reads it.
 *
 * The distinction people most need is not "is this stored" but "does this change the
 * answer, and whose answer". Somebody writing a note deserves to know whether they are
 * teaching the model, feeding a comparison, leaving a message for the next reviewer, or
 * writing to themselves.
 *
 * - `model` — its text is rendered into a prompt as background. It can change what the
 *   model pays attention to and so improve what it finds; it can never make anything
 *   pass or fail (ADR-001).
 * - `code` — code evaluates it against the artifacts. It can make a finding.
 * - `reviewer` — a person reads it later: on the review screen, or on the frozen
 *   report at sign-off. Nothing automated acts on it.
 * - `notes` — your own record. Nothing reads it but you.
 * - `record` — it identifies or files the run: how it is found, grouped and compared
 *   with earlier ones.
 * - `reference` — the AI reads it while somebody sets the product up, and no run
 *   reads it at all. It helps the AI at one remove: what is built from it is what
 *   reaches a run. **This is the one marker an administrator can switch off**
 *   (`ui.setup_markers`), because saying a field is *not* read during a run cannot
 *   mislead anybody about where their words go (ADR-046).
 */
export type FieldEffectKind = "model" | "code" | "reviewer" | "notes" | "record" | "reference";

const EFFECT: Record<
  FieldEffectKind,
  { icon: typeof Cpu; label: string; detail: string; className: string }
> = {
  model: {
    icon: Cpu,
    label: "Helps the AI",
    detail:
      "Rendered into the prompt as background, so the model reads this delivery the way you would. Better context here means better findings. It never makes anything pass or fail on its own — every comparison is made by code.",
    className: "text-info",
  },
  code: {
    icon: Ruler,
    label: "Checked by code",
    detail:
      "Compared against the artifacts by code, not read by the model. It can produce a finding, and the same inputs always give the same answer.",
    className: "text-success",
  },
  reviewer: {
    icon: Users,
    label: "Read by a person",
    detail:
      "Shown to whoever reviews or signs off this run. Nothing automated acts on it, and it reaches no model.",
    className: "text-foreground",
  },
  notes: {
    icon: NotebookPen,
    label: "Your own note",
    detail:
      "Kept with the run for you and anyone looking at it later. It reaches no model and no check.",
    className: "text-muted-foreground",
  },
  record: {
    icon: Tag,
    label: "Identifies the run",
    detail:
      "How this run is found, grouped, and compared with earlier runs of the same configuration. Code checks it against what the uploaded files declare before anything is validated.",
    className: "text-muted-foreground",
  },
  reference: {
    icon: BookOpen,
    label: "Used for setup, not for runs",
    detail:
      "The AI reads this while you set things up, to help you fill things in. It is not used when a delivery is checked — what you build from it here is what a run uses.",
    className: "text-tertiary",
  },
};

/**
 * Say what a field does to a run. Never hidden by `ui.tooltips`, which is help.
 *
 * One kind is optional and the rest are not. `reference` says a field is *read only
 * while you set up* and so can be switched off with `ui.setup_markers`: hiding it
 * cannot mislead anybody about where their words go, and on a screen full of sample
 * files it is the same sentence over and over. The other four say a field reaches the
 * model, is compared by code, is read by a person, or identifies the run — those are
 * the account an administrator gets in place of seeing the prompt, and no setting
 * takes them away (ADR-046).
 *
 * @param kind Which effect this field has.
 * @param note Anything specific to this field — which stages read it, which cap
 *   applies — appended after the standing wording.
 */
export function FieldEffect({
  kind,
  note,
  className,
}: {
  kind: FieldEffectKind;
  note?: string;
  className?: string;
}) {
  const { setupMarkers } = usePalette();
  if (kind === "reference" && !setupMarkers) return null;
  const effect = EFFECT[kind];
  const Icon = effect.icon;
  return (
    <span
      className={cn("inline-flex items-start gap-1 text-xs", effect.className, className)}
      title={note ? `${effect.detail} ${note}` : effect.detail}
    >
      <Icon className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
      <span>
        <span className="font-medium">{effect.label}</span>
        {note ? <span className="text-muted-foreground"> — {note}</span> : null}
      </span>
    </span>
  );
}

/**
 * Explain what a surface is for. Hidden when the deployment switches help off.
 *
 * Rendered as a button rather than a bare icon so it is reachable by keyboard, and
 * removed from the DOM rather than merely hidden when off, so a screen reader is not
 * read a page full of invisible help.
 *
 * **An open tip closes on the next click, wherever it lands** — the control that
 * opened it, the tip's own body, or the far side of the page. Help you have finished
 * reading should not need aiming at to dismiss. That is done with a transparent sheet
 * across the viewport rather than a document listener, because a listener races the
 * button's own handler: whichever of the two runs second decides, and the tip either
 * survives the click or reopens on it. A sheet has no ordering to get wrong — while a
 * tip is open every click lands on the sheet first, and the button underneath never
 * hears it. Keyboard activation dispatches straight to the button and so still
 * toggles, as does Escape.
 *
 * @param children The explanation: what this is for, how to use it, what belongs
 *   elsewhere.
 * @param label What the control announces to a screen reader.
 */
export function Explain({
  children,
  label = "What is this for?",
  className,
}: {
  children: React.ReactNode;
  label?: string;
  className?: string;
}) {
  const { tooltips } = usePalette();
  const [open, setOpen] = React.useState(false);
  if (!tooltips) return null;

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        className="rounded text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <HelpCircle className="h-4 w-4" aria-hidden />
      </button>
      {open ? (
        <>
          <span
            aria-hidden
            data-testid="explain-dismiss"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <span
            role="note"
            className="absolute left-5 top-0 z-50 w-72 rounded-md border border-border bg-background p-3 text-xs leading-relaxed shadow-lg"
            onClick={() => setOpen(false)}
          >
            {children}
          </span>
        </>
      ) : null}
    </span>
  );
}

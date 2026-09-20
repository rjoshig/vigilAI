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

import { Cpu, HelpCircle, Ruler, BookOpen } from "lucide-react";
import * as React from "react";

import { usePalette } from "@/components/palette-provider";
import { cn } from "@/lib/utils";

/**
 * What a field does to a run.
 *
 * - `model` — its text is rendered into a prompt as background. It can change what the
 *   model pays attention to; it can never make anything pass or fail (ADR-001).
 * - `code` — code evaluates it against the artifacts. It can make a finding.
 * - `reference` — neither. It is read by people, or it is a specimen the tool measures
 *   other things against.
 */
export type FieldEffectKind = "model" | "code" | "reference";

const EFFECT: Record<
  FieldEffectKind,
  { icon: typeof Cpu; label: string; detail: string; className: string }
> = {
  model: {
    icon: Cpu,
    label: "Reaches the model",
    detail:
      "Rendered into the prompt as background. It changes what the model pays attention to; it never makes anything pass or fail on its own.",
    className: "text-info",
  },
  code: {
    icon: Ruler,
    label: "Evaluated by code",
    detail:
      "Compared against the artifacts by code, not read by the model. It can produce a finding.",
    className: "text-success",
  },
  reference: {
    icon: BookOpen,
    label: "Reference only",
    detail:
      "Read by people, or used as a specimen other definitions resolve against. It does not reach a prompt and nothing is compared against it.",
    className: "text-muted-foreground",
  },
};

/**
 * Say what a field does to a run. Always shown, whatever `ui.tooltips` says.
 *
 * @param kind Which of the three effects this field has.
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
        <span
          role="note"
          className="absolute left-5 top-0 z-50 w-72 rounded-md border border-border bg-background p-3 text-xs leading-relaxed shadow-lg"
        >
          {children}
        </span>
      ) : null}
    </span>
  );
}

"use client";

/**
 * What is left of a prompt's context allowance (Phase 6.17b).
 *
 * A field that states its cap tells somebody the rule. This tells them what is
 * *left*, which is the thing they can act on: the eleventh configuration note on a
 * configuration is trimmed whether or not anybody knew the rule, and its author finds
 * out afterwards, if at all.
 *
 * Two numbers, because two caps apply and they fail differently. The per-field cap
 * truncates *this* text at a word boundary. The block cap drops whole lines, oldest
 * first, from everything an administrator contributes to one prompt — so a field can
 * be well under its own cap and still be the one that pushes the block over.
 */

import * as React from "react";

import { api, ApiError } from "@/lib/api";
import type { PromptBudget } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A count of characters, grouped, so four figures are readable at a glance. */
function chars(value: number): string {
  return value.toLocaleString();
}

/**
 * Show what this field and the whole prompt have left.
 *
 * @param value The text currently in the field, counted live as it is typed.
 * @param scopeCode The delivery programme whose standing context to count, if any.
 * @param configurationId The configuration whose notes to count, if any.
 */
export function CapMeter({
  value,
  scopeCode = "",
  configurationId = "",
  className,
}: {
  value: string;
  scopeCode?: string;
  configurationId?: string;
  className?: string;
}) {
  const [budget, setBudget] = React.useState<PromptBudget | null>(null);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.getPromptBudget(scopeCode, configurationId);
        if (live) setBudget(found);
      } catch (caught) {
        // A budget nobody could fetch is not worth an error state on a form: the
        // caps still apply and the field still works. Say nothing rather than
        // interrupt somebody writing.
        if (!(caught instanceof ApiError)) throw caught;
      }
    })();
    return () => {
      live = false;
    };
  }, [scopeCode, configurationId]);

  const used = value.trim().length;
  const fieldCap = budget?.per_field_cap ?? 1500;
  const fieldLeft = fieldCap - used;
  const overField = fieldLeft < 0;

  // What the block has left, once this field's text is counted toward it. The stored
  // value is already in `used` when the field is unedited, so this is an estimate
  // while typing and exact once saved — which is the honest way round.
  const blockLeft = budget ? budget.remaining : null;

  return (
    <span className={cn("text-[0.7rem]", className)}>
      <span className={cn(overField ? "font-medium text-destructive" : "text-muted-foreground")}>
        {overField
          ? `${chars(-fieldLeft)} over this field's ${chars(fieldCap)}-character cap — the rest is cut`
          : `${chars(fieldLeft)} characters left in this field`}
      </span>
      {budget ? (
        <span
          className={cn("ml-2", budget.trimmed ? "font-medium text-warn" : "text-muted-foreground")}
        >
          {budget.trimmed
            ? `· the prompt is over its ${chars(budget.block_cap)}-character total and oldest lines are being dropped`
            : `· ${chars(blockLeft ?? 0)} left across everything in this prompt`}
        </span>
      ) : null}
    </span>
  );
}

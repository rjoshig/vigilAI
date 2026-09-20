"use client";

/**
 * Every admin delete asks the person to type `delete` (ADR-032).
 *
 * The button opens an inline prompt in place; the word is passed through to the API,
 * which refuses a delete without it, so a script cannot skip the pause the screen
 * imposes. `compact` fits inside a chip.
 */

import { Trash2 } from "lucide-react";
import * as React from "react";

import { Button, Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export const DELETE_WORD = "delete";

interface DeleteButtonProps {
  /** What is being deleted, for the accessible name: "the alias score_v3". */
  label: string;
  busy?: boolean;
  disabled?: boolean;
  compact?: boolean;
  /** Runs with the typed word once it matches. */
  onDelete: (confirm: string) => Promise<void> | void;
}

export function DeleteButton({ label, busy, disabled, compact, onDelete }: DeleteButtonProps) {
  const [open, setOpen] = React.useState(false);
  const [typed, setTyped] = React.useState("");

  if (!open) {
    return (
      <button
        type="button"
        aria-label={`Delete ${label}`}
        disabled={busy || disabled}
        className={cn(
          "inline-flex items-center justify-center rounded text-muted-foreground hover:text-destructive disabled:opacity-50",
          compact ? "h-4 w-4" : "h-7 w-7 border"
        )}
        onClick={() => setOpen(true)}
      >
        <Trash2 className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
      </button>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/5 p-1",
        compact ? "text-[0.7rem]" : "text-xs"
      )}
      data-testid="confirm-delete"
    >
      <span className="whitespace-nowrap">
        Type <span className="mono font-semibold">{DELETE_WORD}</span>
      </span>
      <Input
        className={cn("mono h-6 text-xs", compact ? "w-16" : "w-20")}
        autoComplete="off"
        autoFocus
        aria-label={`Type ${DELETE_WORD} to delete ${label}`}
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
      <Button
        size="xs"
        variant="destructive"
        disabled={busy || typed.trim().toLowerCase() !== DELETE_WORD}
        onClick={async () => {
          await onDelete(typed.trim());
          setOpen(false);
          setTyped("");
        }}
      >
        {DELETE_WORD}
      </Button>
      <Button
        size="xs"
        variant="ghost"
        onClick={() => {
          setOpen(false);
          setTyped("");
        }}
      >
        Cancel
      </Button>
    </span>
  );
}

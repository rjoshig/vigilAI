"use client";

/**
 * Select many rows, act once (ADR-032). One typed word covers the whole batch: the
 * word is the action for state changes and `delete` for deletes.
 */

import * as React from "react";

import { Button, Input, Select } from "@/components/ui/primitives";

export interface BulkAction {
  /** The word the person types, and the value sent to the API. */
  word: string;
  label: string;
  destructive?: boolean;
}

interface BulkBarProps {
  count: number;
  actions: BulkAction[];
  busy?: boolean;
  onClear: () => void;
  onAct: (word: string) => Promise<void> | void;
}

export function BulkBar({ count, actions, busy, onClear, onAct }: BulkBarProps) {
  const [action, setAction] = React.useState(actions[0]?.word ?? "");
  const [typed, setTyped] = React.useState("");
  if (count === 0) return null;
  const chosen = actions.find((one) => one.word === action) ?? actions[0];

  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 p-2 text-xs"
      data-testid="bulk-bar"
    >
      <span className="font-semibold">{count} selected</span>
      {actions.length > 1 ? (
        <Select
          className="h-7 text-xs"
          aria-label="Bulk action"
          value={action}
          onChange={(event) => setAction(event.target.value)}
        >
          {actions.map((one) => (
            <option key={one.word} value={one.word}>
              {one.label}
            </option>
          ))}
        </Select>
      ) : (
        <span>{chosen.label}</span>
      )}
      <span>
        Type <span className="mono font-semibold">{chosen.word}</span> to confirm
      </span>
      <Input
        className="mono h-7 w-24 text-xs"
        autoComplete="off"
        aria-label={`Type ${chosen.word} to confirm`}
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
      <Button
        size="xs"
        variant={chosen.destructive ? "destructive" : "default"}
        disabled={busy || typed.trim().toLowerCase() !== chosen.word}
        onClick={async () => {
          await onAct(typed.trim());
          setTyped("");
        }}
      >
        {chosen.label}
      </Button>
      <Button size="xs" variant="ghost" onClick={onClear}>
        Clear selection
      </Button>
    </div>
  );
}

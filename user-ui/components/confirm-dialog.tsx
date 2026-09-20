"use client";

/**
 * "Are you sure?" for the user console (ADR-032).
 *
 * The user app has no delete today; when one arrives it uses this, so a person is
 * asked once, plainly, and never made to type a word: the admin console carries the
 * heavier confirmation because its changes reach every run.
 */

import * as React from "react";

import { Button } from "@/components/ui/primitives";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** What happens if they say yes, in a sentence. */
  detail?: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => Promise<void> | void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  detail,
  confirmLabel = "Yes, continue",
  busy,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-sm rounded-lg border bg-card p-4 text-card-foreground shadow-lg">
        <h2 id="confirm-title" className="text-sm font-semibold">
          {title}
        </h2>
        {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="xs" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" size="xs" onClick={() => void onConfirm()} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

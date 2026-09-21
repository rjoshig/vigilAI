"use client";

/**
 * Do these artifacts belong to the delivery you described? (Phase 6.14a, ADR-041)
 *
 * A run submitted with the wrong customer or the wrong configuration id used to be
 * validated thoroughly against the wrong premise and read as a normal result. The
 * comparison is made by code before the model is asked anything, and where it
 * disagrees the run waits here.
 *
 * The files are already stored, so clearing this costs a reason and a click — never a
 * re-upload. Anyone who can submit a run can accept one; who ought to be consulted
 * first is a question for the delivery process, not a permission in the tool.
 *
 * Once accepted the panel stays, showing what was waived and why, because a reviewer
 * signing the delivery should see it.
 *
 * **There are two ways out, and there has to be.** Accepting says the artifacts belong
 * together. Cancelling says the form was wrong. Only the first was ever offered here,
 * so somebody who had simply mistyped a configuration id had one button and it asserted
 * something untrue — and that assertion is printed on the final report over their name.
 * A hold with one exit is a hold that teaches people to write a reason they do not mean.
 * `POST /runs/{id}/cancel` has accepted a held run since the hold existed; nothing in
 * the product called it.
 */

import { AlertTriangle, ArrowRight, Check, Play, X } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ArtifactMismatch } from "@/lib/types";

interface ArtifactMatchCardProps {
  runId: number;
  mismatches: ArtifactMismatch[];
  /** True while the run is held: the accept control is only shown then. */
  held: boolean;
  /** Called once the run has been accepted or cancelled, so the page re-reads it. */
  onAccepted?: () => void;
}

/**
 * Reasons offered as one-click chips.
 *
 * Typing the same sentence every time is how a required field becomes a formality, so
 * the common answers are one tap and the box stays editable for the case nobody
 * anticipated. They are suggestions, never a closed list.
 */
const COMMON_REASONS: readonly string[] = [
  "Typed the wrong value on the form; the files are right.",
  "The customer has been renamed since the configuration was written.",
  "Re-running an archived delivery under its original identity.",
  "The configuration was copied from another delivery and not re-labelled.",
];

export function ArtifactMatchCard({ runId, mismatches, held, onAccepted }: ArtifactMatchCardProps) {
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (mismatches.length === 0) return null;

  const outstanding = mismatches.filter((m) => !m.accepted_at);

  async function accept() {
    if (!reason.trim()) {
      setError("Say why these artifacts are the delivery you meant.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.acceptMismatches(runId, reason.trim());
      onAccepted?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not accept.");
    } finally {
      setBusy(false);
    }
  }

  /**
   * The other way out: the artifacts are fine and the form was wrong.
   *
   * No reason is asked for, because there is nothing to waive — the run is discarded
   * rather than validated against a premise nobody stands behind. Nothing has been sent
   * to the model at this point, so it costs what it says it costs.
   */
  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api.cancelRun(runId);
      onAccepted?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not cancel the run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4 border-warn">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-warn" aria-hidden />
          {held
            ? "These artifacts do not match what you submitted"
            : "The artifacts did not match what was submitted"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm text-muted-foreground">
          {held ? (
            <>
              Nothing has been validated yet. The files are uploaded and safe — check the values
              below, then accept to run, or go back and correct the form.
            </>
          ) : (
            <>Accepted before the run started. Kept here so it is visible at sign-off.</>
          )}
        </p>

        <ul className="mb-4 grid gap-2">
          {mismatches.map((mismatch) => (
            <li
              key={mismatch.id}
              className="rounded-md border border-border bg-muted/40 p-3 text-sm"
            >
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="font-medium">{mismatch.label}</span>
                {mismatch.kind === "near" ? (
                  <Badge tone="warn">nearly the same</Badge>
                ) : (
                  <Badge tone="destructive">different</Badge>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                <span className="rounded bg-background px-2 py-1">
                  you submitted: {mismatch.submitted || "(nothing)"}
                </span>
                <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />
                <span className="rounded bg-background px-2 py-1">
                  the file says: {mismatch.declared || "(nothing)"}
                </span>
              </div>
              {mismatch.source ? (
                <p className="mt-1 text-xs text-muted-foreground">Read from {mismatch.source}.</p>
              ) : null}
              {mismatch.accepted_at ? (
                <p className="mt-2 flex items-start gap-1 text-xs text-muted-foreground">
                  <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" aria-hidden />
                  <span>
                    Accepted by {mismatch.accepted_by}: &ldquo;{mismatch.reason}&rdquo;
                  </span>
                </p>
              ) : null}
            </li>
          ))}
        </ul>

        {held && outstanding.length > 0 ? (
          <div className="grid gap-2">
            <label htmlFor="match-reason" className="text-sm font-medium">
              Why are these the right artifacts?
            </label>
            <div className="flex flex-wrap gap-1">
              {COMMON_REASONS.map((text) => (
                <Button
                  key={text}
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-auto py-1 text-xs font-normal"
                  onClick={() => setReason(text)}
                >
                  {text}
                </Button>
              ))}
            </div>
            <Textarea
              id="match-reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Pick one above, or write your own."
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => void accept()} disabled={busy}>
                <Play className="mr-1 h-4 w-4" aria-hidden />
                {busy ? "Starting…" : "Accept and run"}
              </Button>
              <Button variant="outline" onClick={() => void cancel()} disabled={busy}>
                <X className="mr-1 h-4 w-4" aria-hidden />
                {busy ? "Cancelling…" : "The form was wrong — cancel"}
              </Button>
              <span className="text-xs text-muted-foreground">
                Accepting is recorded with your name and shown on the final report. Cancelling costs
                nothing: no model call has been made.
              </span>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

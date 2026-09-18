"use client";

/**
 * The observations a person has written, and what became of them (ADR-021, 6.1e).
 *
 * An author who cannot see what happened to what they wrote stops writing, so this
 * page exists for the status and, on a rejection, the administrator's reason.
 */

import { Lightbulb, Pencil } from "lucide-react";
import * as React from "react";

import { ObservationDialog, useTrainingEnabled } from "@/components/observation-dialog";
import {
  Badge,
  Card,
  CardContent,
  Button,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Observation, ObservationStatus } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

/** What each status means to the person who wrote the observation. */
const STATUS_TEXT: Record<ObservationStatus, string> = {
  new: "Waiting for an administrator to look at it",
  queued: "An administrator has picked it up",
  synthesized: "The model has drafted a rule from it, for an administrator to approve",
  rejected: "Not taken forward",
  superseded: "Replaced by a later observation",
};

const STATUS_TONE: Record<ObservationStatus, "muted" | "info" | "success" | "destructive"> = {
  new: "muted",
  queued: "info",
  synthesized: "success",
  rejected: "destructive",
  superseded: "muted",
};

export default function ObservationsPage() {
  const enabled = useTrainingEnabled();
  const [observations, setObservations] = React.useState<Observation[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<Observation | null>(null);

  const load = React.useCallback(async () => {
    try {
      setObservations(await api.listMyObservations());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load your observations.");
    }
  }, []);

  // No training endpoint is called while the mode is off, which is the shipped default.
  React.useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  if (!enabled) {
    return (
      <EmptyState
        title="Train AI mode is off"
        hint="An administrator switches it on. Until then there is nothing to record."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="My observations"
        description="What you have told the tool it should check. Observations never run: an administrator reviews them and the model drafts a rule they approve. Raise one from a finding on any run."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      {observations === null ? (
        <Skeleton className="h-48" />
      ) : observations.length === 0 ? (
        <EmptyState
          title="You have not written any yet"
          hint="Open a run, press “What should this check?” on a finding, and say what you know."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {observations.map((observation) => (
            <Card key={observation.id} className="p-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <Lightbulb className="h-4 w-4 text-primary" />
                <span className="min-w-[12rem] flex-1 text-sm font-semibold">
                  {observation.statement}
                </span>
                <Badge tone={STATUS_TONE[observation.status]}>{observation.status}</Badge>
                {observation.editable ? (
                  <Button variant="ghost" size="xs" onClick={() => setEditing(observation)}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                ) : null}
              </div>

              {observation.expectation ? (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Expected: {observation.expectation}
                </p>
              ) : null}

              <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
                {STATUS_TEXT[observation.status]} · {observation.kind} · severity{" "}
                {observation.severity_hint} · scope {observation.scope_hint} ·{" "}
                {fmtTime(observation.created_at)}
                {observation.run_id ? ` · run VR-${String(observation.run_id).padStart(4, "0")}` : ""}
              </p>

              {observation.status === "rejected" && observation.status_note ? (
                <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs">
                  <span className="font-semibold">Why it was not taken forward: </span>
                  {observation.status_note}
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <Card className="mt-4">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Nothing here changes a run on its own. A rule only starts producing findings once an
          administrator has approved it and it has been through shadow mode.
        </CardContent>
      </Card>

      {editing ? (
        <ObservationDialog
          anchors={editing.anchors}
          existing={editing}
          context={`Observation #${editing.id}`}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

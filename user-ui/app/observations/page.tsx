"use client";

/**
 * The observations a person has written, and what became of them (ADR-021, 6.1e).
 *
 * An author who cannot see what happened to what they wrote stops writing, so this
 * page exists for the status and, on a rejection, the administrator's reason.
 */

import { Lightbulb, Pencil } from "lucide-react";
import * as React from "react";

import {
  KINDS,
  ObservationDialog,
  SCOPES,
  useTrainingEnabled,
} from "@/components/observation-dialog";
import { TrainAiTag } from "@/components/train-ai-tag";
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
import { OUTCOME_LABEL, SEVERITY_LABEL } from "@/lib/display";
import type { Observation, ObservationOutcome } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

/** How each outcome reads as a badge. */
const OUTCOME_BADGE: Record<ObservationOutcome, string> = {
  waiting: "Waiting",
  drafted: "Drafted",
  approved: "In shadow",
  live: "Live",
  disabled: "Switched off",
  rejected: "Not taken forward",
};

const OUTCOME_TONE: Record<ObservationOutcome, "muted" | "info" | "success" | "destructive"> = {
  waiting: "muted",
  drafted: "info",
  approved: "info",
  live: "success",
  disabled: "muted",
  rejected: "destructive",
};

/** The chain an observation travels, so the author sees where theirs is. */
const CHAIN: ObservationOutcome[] = ["waiting", "drafted", "approved", "live"];

function label<T extends string>(options: { value: T; label: string }[], value: T): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

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
        title={
          <>
            My observations <TrainAiTag />
          </>
        }
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
                <Badge tone={OUTCOME_TONE[observation.outcome]} data-testid="outcome">
                  {OUTCOME_BADGE[observation.outcome]}
                </Badge>
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

              <p className="mt-1.5 text-xs">{OUTCOME_LABEL[observation.outcome]}</p>

              {observation.outcome !== "rejected" ? (
                <ol
                  className="mt-1.5 flex flex-wrap items-center gap-1 text-[0.68rem]"
                  aria-label="Progress"
                >
                  {CHAIN.map((step, index) => {
                    const reached = CHAIN.indexOf(observation.outcome) >= index;
                    return (
                      <li key={step} className="flex items-center gap-1">
                        {index > 0 ? <span className="text-muted-foreground">→</span> : null}
                        <span
                          className={
                            reached ? "font-semibold text-foreground" : "text-muted-foreground"
                          }
                        >
                          {OUTCOME_BADGE[step]}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              ) : null}

              {observation.rule_ref ? (
                <p className="mt-1.5 text-xs" data-testid="became-rule">
                  <span className="font-semibold">Became rule:</span> {observation.rule_name}{" "}
                  <span className="mono text-muted-foreground">{observation.rule_summary}</span>
                </p>
              ) : null}

              <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
                {label(KINDS, observation.kind)} · {SEVERITY_LABEL[observation.severity_hint]} ·{" "}
                {label(SCOPES, observation.scope_hint)} · {fmtTime(observation.created_at)}
                {observation.run_id
                  ? ` · run VR-${String(observation.run_id).padStart(4, "0")}`
                  : ""}
              </p>

              {observation.outcome === "rejected" && observation.outcome_note ? (
                <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs">
                  <span className="font-semibold">Why it was not taken forward: </span>
                  {observation.outcome_note}
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <Card className="mt-4">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Nothing here changes a run on its own. A rule an administrator approves runs in shadow
          first — counted, shown to nobody — and produces findings only once it is made live. Each
          card above says where yours has got to.
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

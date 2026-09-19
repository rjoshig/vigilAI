"use client";

/**
 * The training queue (ADR-021). A reviewer's sentence becomes a rule only by passing
 * through a person here: the model drafts a candidate, code has already validated it,
 * and an administrator approves it into shadow.
 */

import { GraduationCap, Sparkles } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Anchor, Candidate, Observation } from "@/lib/types";

/** An anchor on one line: what the person pointed at, as they pointed at it. */
function anchorText(anchor: Anchor): string {
  const parts = [anchor.artifact, anchor.sheet, anchor.cell, anchor.field, anchor.reference];
  const located = parts.filter((part) => part).join(" · ");
  const where = located || anchor.kind;
  return anchor.value ? `${where} = ${anchor.value}` : where;
}

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** The drafted rule in the plainest readable form its body allows. */
function bodyLines(body: Record<string, unknown>): string[] {
  return Object.entries(body).map(([key, value]) => {
    const rendered =
      typeof value === "string" || typeof value === "number" || typeof value === "boolean"
        ? String(value)
        : JSON.stringify(value);
    return `${key}: ${rendered}`;
  });
}

/** A reason is required, because it is what the author of the observation reads. */
function ReasonForm({
  label,
  busy,
  onSubmit,
}: {
  label: string;
  busy: boolean;
  onSubmit: (reason: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");

  if (!open) {
    return (
      <Button variant="outline" size="xs" disabled={busy} onClick={() => setOpen(true)}>
        {label}
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Input
        className="h-7 w-56 text-xs"
        aria-label="Reason"
        placeholder="the reason the author sees"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <Button
        variant="destructive"
        size="xs"
        disabled={busy || reason.trim().length === 0}
        onClick={() => {
          onSubmit(reason.trim());
          setReason("");
          setOpen(false);
        }}
      >
        {label}
      </Button>
      <Button variant="ghost" size="xs" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </div>
  );
}

export default function TrainingPage() {
  const [observations, setObservations] = React.useState<Observation[] | null>(null);
  const [candidates, setCandidates] = React.useState<Candidate[]>([]);
  const [selected, setSelected] = React.useState<number[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  // A 404 on the observations list means the mode is switched off, which is a state
  // to explain rather than an error to report.
  const [off, setOff] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const loaded = await api.listObservations("new");
      setObservations(loaded);
      setOff(false);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        setOff(true);
        setObservations([]);
        return;
      }
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
      return;
    }
    try {
      setCandidates(await api.listCandidates("draft"));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not read the candidates.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: number) {
    setSelected((current) =>
      current.includes(id) ? current.filter((one) => one !== id) : [...current, id]
    );
  }

  if (off) {
    return (
      <>
        <PageHeader
          title="Training"
          description="Turning what reviewers know into rules, one approval at a time."
        />
        <Card>
          <CardContent className="p-6">
            <p className="text-sm font-medium">Train AI mode is off.</p>
            <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
              While it is off, nobody can file an observation and there is nothing to review here.
              Switch <span className="mono">training.enabled</span> on from the Settings screen to
              start collecting them.
            </p>
          </CardContent>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Training"
        description="What reviewers wrote, and what the model made of it. The model only drafts: nothing here runs until an administrator approves it, and an approved rule starts in shadow."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b">
            <CardTitle className="flex items-center gap-2">
              <GraduationCap className="h-4 w-4 text-muted-foreground" />
              Observations
            </CardTitle>
            <Button
              size="xs"
              disabled={busy || selected.length === 0}
              onClick={() =>
                void act("synthesize the selection", async () => {
                  await api.synthesize(selected);
                  setSelected([]);
                })
              }
            >
              <Sparkles className="h-3.5 w-3.5" /> Synthesize selected ({selected.length})
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {!observations ? (
              <Skeleton className="m-4 h-56" />
            ) : observations.length === 0 ? (
              <EmptyState
                title="Nothing waiting"
                hint="Observations filed by reviewers arrive here."
              />
            ) : (
              <ul>
                {observations.map((observation) => (
                  <li key={observation.id} className="border-b p-3 last:border-b-0">
                    <div className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 rounded border-input"
                        aria-label={`Select observation ${observation.id}`}
                        checked={selected.includes(observation.id)}
                        onChange={() => toggle(observation.id)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-xs font-semibold">
                            {observation.author || "unattributed"}
                          </span>
                          <Badge tone="outline">{observation.kind}</Badge>
                          <Badge tone="muted">{observation.severity_hint}</Badge>
                          {observation.customer_name ? (
                            <Badge tone="info">{observation.customer_name}</Badge>
                          ) : null}
                          <span className="text-[0.7rem] text-muted-foreground">
                            {when(observation.created_at)}
                          </span>
                        </div>
                        {/* Shown as the person's words, never as something the console
                            acts on: only an approved candidate ever runs. */}
                        <p className="mt-1 text-sm">{observation.statement}</p>
                        {observation.expectation ? (
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            Expected: {observation.expectation}
                          </p>
                        ) : null}
                        <div className="mt-1 flex flex-wrap gap-1">
                          {observation.anchors.map((anchor, index) => (
                            <span
                              key={`${observation.id}-${index}`}
                              className="mono rounded bg-muted px-1.5 py-0.5 text-[0.7rem] text-muted-foreground"
                            >
                              {anchorText(anchor)}
                            </span>
                          ))}
                        </div>
                        <div className="mt-2">
                          <ReasonForm
                            label="Reject"
                            busy={busy}
                            onSubmit={(reason) =>
                              void act("reject the observation", () =>
                                api.rejectObservation(observation.id, reason)
                              )
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Candidate rules</CardTitle>
            <span className="text-[0.7rem] text-muted-foreground">
              Approving puts a rule into shadow, not into use.
            </span>
          </CardHeader>
          <CardContent className="p-0">
            {candidates.length === 0 ? (
              <EmptyState
                title="No candidates"
                hint="Select observations on the left and synthesize them."
              />
            ) : (
              <ul>
                {candidates.map((candidate) => (
                  <li key={candidate.id} className="border-b p-3 last:border-b-0">
                    <CandidateCard
                      candidate={candidate}
                      busy={busy}
                      onAct={(what, run) => void act(what, run)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

/** One drafted rule, with everything an administrator needs before deciding. */
function CandidateCard({
  candidate,
  busy,
  onAct,
}: {
  candidate: Candidate;
  busy: boolean;
  onAct: (what: string, run: () => Promise<unknown>) => void;
}) {
  const replay = candidate.replay;
  const replayed = Object.keys(replay).length > 0;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mono text-sm font-semibold">{candidate.name || "unnamed"}</span>
        <Badge tone="outline">{candidate.target_kind}</Badge>
        <Badge tone="muted">{candidate.severity}</Badge>
        <Badge tone="info">{candidate.scope}</Badge>
        {candidate.status === "rejected" ? <Badge tone="destructive">rejected</Badge> : null}
      </div>

      <dl className="mono mt-1.5 rounded-md bg-muted/50 p-2 text-[0.7rem]">
        {bodyLines(candidate.body).map((line) => (
          <div key={line}>{line}</div>
        ))}
      </dl>

      <p className="mt-1.5 text-xs">{candidate.reasoning}</p>
      <p className="mt-0.5 text-[0.7rem] text-muted-foreground">
        From observation{candidate.source_observation_ids.length === 1 ? "" : "s"}{" "}
        {candidate.source_observation_ids.join(", ") || "—"} · drafted by{" "}
        {candidate.model_used || "the model"} · prompt {candidate.prompt_version || "—"}
      </p>

      {candidate.conflicts.length > 0 ? (
        <div className="mt-1.5 rounded-md border border-warn/40 bg-warn/10 p-2 text-[0.7rem]">
          <span className="font-semibold">Overlaps a rule that already runs.</span>
          <ul className="mt-0.5">
            {candidate.conflicts.map((conflict) => (
              <li key={`${conflict.rule_kind}-${conflict.id}`}>
                {conflict.rule_kind} #{conflict.id} · {conflict.summary} · {conflict.scope} ·{" "}
                {conflict.state}
                {conflict.same ? " · says the same thing" : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {replayed ? (
        <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
          Replay: {replay.runs_examined ?? 0} runs examined, {replay.related_findings ?? 0} related
          findings, {replay.previously_dismissed ?? 0} of them already dismissed.
          {replay.note ? ` ${replay.note}` : ""}
        </p>
      ) : null}

      {candidate.status === "rejected" ? (
        <p className="mt-1.5 text-xs text-destructive">
          Reason given: {candidate.admin_note || "none recorded"}
        </p>
      ) : (
        <>
          <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
            Approving creates the rule in <span className="font-semibold">shadow</span>: it runs and
            its findings are counted, but no reviewer sees them until it is activated on the Rules
            screen.
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Button
              variant="outline"
              size="xs"
              disabled={busy}
              onClick={() => onAct("replay the candidate", () => api.replayCandidate(candidate.id))}
            >
              {replayed ? "Replay again" : "Replay"}
            </Button>
            <Button
              size="xs"
              disabled={busy}
              onClick={() =>
                onAct("approve the candidate", () => api.approveCandidate(candidate.id))
              }
            >
              Approve into shadow
            </Button>
            <ReasonForm
              label="Reject"
              busy={busy}
              onSubmit={(reason) =>
                onAct("reject the candidate", () => api.rejectCandidate(candidate.id, reason))
              }
            />
          </div>
        </>
      )}
    </div>
  );
}

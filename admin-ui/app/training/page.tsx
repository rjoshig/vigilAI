"use client";

/**
 * The training queue (ADR-021). A reviewer's sentence becomes a rule only by passing
 * through a person here: the model drafts a candidate, code has already validated it,
 * and an administrator approves it into shadow.
 */

import { GraduationCap, Sparkles } from "lucide-react";
import * as React from "react";

import { Explain } from "@/components/explain";
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

/** Which kinds the queue shows. A configuration note is an observation too (ADR-024). */
type QueueFilter = "all" | "observations" | "config_notes";

const FILTERS: { value: QueueFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "observations", label: "Observations" },
  { value: "config_notes", label: "Configuration notes" },
];

/**
 * The configuration every selected item is a note on, or null. The backend scopes a
 * candidate to `config:<id>` on its own when this holds; the console only says so.
 */
function sharedConfiguration(observations: Observation[], selected: number[]): string | null {
  const chosen = observations.filter((one) => selected.includes(one.id));
  if (chosen.length === 0) return null;
  const first = chosen[0];
  if (first.kind !== "config_note") return null;
  const same = chosen.every(
    (one) => one.kind === "config_note" && one.configuration_id === first.configuration_id
  );
  return same ? first.configuration_id : null;
}

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

/** The earlier wordings of a note, kept because the record of what was said matters. */
function EarlierWordings({ observation }: { observation: Observation }) {
  const [open, setOpen] = React.useState(false);
  if (observation.revisions.length === 0) return null;
  const count = observation.revisions.length;

  return (
    <div className="mt-1">
      <button
        type="button"
        className="text-[0.7rem] text-muted-foreground underline-offset-2 hover:underline"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "Hide" : "Show"} earlier wording{count === 1 ? "" : "s"} ({count})
      </button>
      {open ? (
        <ul className="mt-1 space-y-1 border-l-2 pl-2">
          {observation.revisions.map((revision) => (
            <li key={revision.version} className="text-xs">
              <span className="text-[0.7rem] text-muted-foreground">
                v{revision.version} · {revision.by || "unattributed"} · {when(revision.at)}
              </span>
              <p className="text-muted-foreground">{revision.statement}</p>
            </li>
          ))}
        </ul>
      ) : null}
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
  const [filter, setFilter] = React.useState<QueueFilter>("all");

  const load = React.useCallback(async () => {
    try {
      // The API filters by kind but not by its absence, so "Observations" is narrowed
      // here after the full list arrives.
      const loaded = await api.listObservations(
        "new",
        filter === "config_notes" ? "config_note" : ""
      );
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
  }, [filter]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const shown = (observations ?? []).filter(
    (observation) => filter !== "observations" || observation.kind !== "config_note"
  );
  const scopedTo = sharedConfiguration(shown, selected);

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

  // A replay is a worker job now (Phase 6.13e), so the screen waits for it rather than
  // showing a result the request could not have had.
  const waiting = candidates.some((candidate) => candidate.replay?.status === "running");
  React.useEffect(() => {
    if (!waiting) return undefined;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [waiting, load]);

  function toggle(id: number) {
    setSelected((current) =>
      current.includes(id) ? current.filter((one) => one !== id) : [...current, id]
    );
  }

  if (off) {
    return (
      <>
        <PageHeader
          explain={
            <Explain label="What the queue is">
              What associates wrote, in their own words, waiting for you. The model drafts a rule
              from each, code checks it for overlap with rules that already exist, and a replay
              shows what it would have changed on past runs.
              <br />
              <br />
              You are approving a case the model assembled, not writing a specification. Approving
              lands it in <b>shadow</b>, where it runs and is counted and nobody sees it until you
              activate it.
            </Explain>
          }
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
            <div className="flex flex-wrap items-center gap-2">
              {scopedTo ? (
                <span className="text-[0.7rem] text-muted-foreground">
                  The rule will be scoped to configuration <span className="mono">{scopedTo}</span>
                </span>
              ) : null}
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
            </div>
          </CardHeader>
          <div
            className="flex flex-wrap items-center gap-1 border-b px-3 py-2"
            role="group"
            aria-label="Show"
          >
            {FILTERS.map((option) => (
              <Button
                key={option.value}
                variant={filter === option.value ? "secondary" : "ghost"}
                size="xs"
                aria-pressed={filter === option.value}
                onClick={() => setFilter(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <CardContent className="p-0">
            {!observations ? (
              <Skeleton className="m-4 h-56" />
            ) : shown.length === 0 ? (
              <EmptyState
                title="Nothing waiting"
                hint={
                  filter === "config_notes"
                    ? "Notes written against a configuration arrive here."
                    : "Observations filed by reviewers arrive here."
                }
              />
            ) : (
              <ul>
                {shown.map((observation) => (
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
                          {observation.kind === "config_note" ? (
                            <>
                              <Badge tone="info">Configuration note</Badge>
                              <span className="mono text-sm font-semibold">
                                {observation.configuration_id || "—"}
                              </span>
                              <Badge tone={observation.is_active ? "success" : "muted"}>
                                {observation.is_active ? "active" : "switched off"}
                              </Badge>
                            </>
                          ) : (
                            <>
                              <Badge tone="outline">{observation.kind}</Badge>
                              <Badge tone="muted">{observation.severity_hint}</Badge>
                              {observation.customer_name ? (
                                <Badge tone="info">{observation.customer_name}</Badge>
                              ) : null}
                            </>
                          )}
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
                        {observation.kind === "config_note" ? (
                          <EarlierWordings observation={observation} />
                        ) : null}
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          {observation.kind === "config_note" ? (
                            // Off stops the note reaching the model on the next run; the
                            // text is kept, so it can be switched back on (ADR-024).
                            <Button
                              variant="outline"
                              size="xs"
                              disabled={busy}
                              onClick={() =>
                                void act(
                                  observation.is_active
                                    ? "switch the note off"
                                    : "switch the note on",
                                  () =>
                                    api.setConfigNoteActive(observation.id, !observation.is_active)
                                )
                              }
                            >
                              {observation.is_active ? "Switch off" : "Switch on"}
                            </Button>
                          ) : null}
                          <ReasonForm
                            label="Reject"
                            busy={busy}
                            onSubmit={(reason) =>
                              void act("reject the observation", () =>
                                api.rejectObservation(observation.id, reason)
                              )
                            }
                          />
                          {/* Rejecting says it was considered and not acted on.
                              Withdrawing says it should not have been submitted —
                              the wrong finding, a half-finished sentence — and frees
                              the author to write a fresh one. The row survives. */}
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            title="Take it off every screen and let the author submit again. The record is kept."
                            onClick={() =>
                              void act("withdraw the observation", () =>
                                api.withdrawObservation(observation.id)
                              )
                            }
                          >
                            Withdraw
                          </Button>
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
  const replayed = replay.evaluated === true;

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
                <span className="font-medium">{conflict.name || `#${conflict.id}`}</span> ·{" "}
                {conflict.rule_kind.replace("_", " ")} · {conflict.summary} · {conflict.scope} ·{" "}
                {conflict.state}
                {conflict.same ? " · says the same thing" : ""}
              </li>
            ))}
          </ul>
          <p className="mt-1">
            Approving asks you to choose: replace the older rule, or keep both because they cover
            different ground.
          </p>
        </div>
      ) : null}

      {replay.status === "running" ? (
        <p className="mt-1.5 text-[0.7rem] text-muted-foreground" data-testid="replay-running">
          Replaying: each run&apos;s stored reports are being read again and this rule run over
          them. The result appears here when it finishes.
        </p>
      ) : replayed ? (
        <div className="mt-1.5 text-[0.7rem] text-muted-foreground" data-testid="replay-result">
          <p>
            Replayed against {replay.runs_examined ?? 0} finalized run
            {(replay.runs_examined ?? 0) === 1 ? "" : "s"}: it would have fired on{" "}
            {replay.would_fire_on?.length ?? 0} of them.
            {replay.unreadable ? ` ${replay.unreadable} could not be read back.` : ""}
            {` About ${replay.previously_dismissed ?? 0} related finding${
              (replay.previously_dismissed ?? 0) === 1 ? " was" : "s were"
            } already dismissed by a reviewer (an estimate).`}
          </p>
          {replay.examples && replay.examples.length > 0 ? (
            <ul className="mono mt-0.5 space-y-0.5">
              {replay.examples.map((example) => (
                <li key={example}>{example}</li>
              ))}
            </ul>
          ) : null}
          {replay.note ? <p className="mt-0.5 italic">{replay.note}</p> : null}
        </div>
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
            {candidate.conflicts.length > 0 ? (
              <>
                <Button
                  size="xs"
                  disabled={busy}
                  title="The overlapping rule is disabled and this one takes its place, in shadow"
                  onClick={() =>
                    onAct("approve the candidate and replace the older rule", () =>
                      api.approveCandidate(candidate.id, { resolution: "supersede" })
                    )
                  }
                >
                  Approve — replace the older rule
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  title="Both rules run; you have looked and they cover different ground"
                  onClick={() =>
                    onAct("approve the candidate and keep both rules", () =>
                      api.approveCandidate(candidate.id, { resolution: "keep_both" })
                    )
                  }
                >
                  Approve — keep both
                </Button>
              </>
            ) : (
              <Button
                size="xs"
                disabled={busy}
                onClick={() =>
                  onAct("approve the candidate", () => api.approveCandidate(candidate.id))
                }
              >
                Approve into shadow
              </Button>
            )}
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

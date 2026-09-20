"use client";

/**
 * What this run checked, and what it did not (Phase 6.11c).
 *
 * A findings list says what disagreed. On its own it cannot tell a clean delivery from
 * an unexamined one, which is how a compliance requirement slips through: nothing was
 * wrong because nothing was compared. This panel is the other half of the sentence, and
 * the gaps it lists have to be acknowledged before the report can be frozen (ADR-035).
 *
 * Every number here is produced by code. The model is not involved.
 */

import { AlertTriangle, ClipboardCheck, Eye, Lightbulb } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Coverage, CoverageState, RequirementCoverage } from "@/lib/types";

interface CoverageCardProps {
  runId: number;
  /** Called after an acknowledgement, so the run's gate state is re-read. */
  onChange?: () => void;
  /** False once the run is frozen: the gaps are history, not work. */
  editable?: boolean;
  /**
   * Record what should have been checked, from the gap itself (Phase 6.13b). The tool
   * saying "I did not check this" is exactly when a person knows what should have been.
   * Absent when Train AI mode is off.
   */
  onObserve?: ((entry: RequirementCoverage) => void) | null;
}

const STATE_LABEL: Record<CoverageState, string> = {
  checked: "Checked against a report",
  traced_unchecked: "Traced, no report evidenced it",
  untraced: "Not traced to the configuration",
  manual: "Verified by hand",
};

const STATE_TONE: Record<CoverageState, "success" | "warn" | "destructive" | "info"> = {
  checked: "success",
  traced_unchecked: "warn",
  untraced: "destructive",
  manual: "info",
};

/** The states the gate asks a person to acknowledge. */
function needsAcknowledging(entry: RequirementCoverage): boolean {
  return entry.state === "traced_unchecked" || entry.state === "manual";
}

export function CoverageCard({ runId, onChange, editable = true, onObserve }: CoverageCardProps) {
  const [coverage, setCoverage] = React.useState<Coverage | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [open, setOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setCoverage(await api.getCoverage(runId));
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.detail : "Could not read what this run checked."
      );
    }
  }, [runId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function acknowledge(targets: string[]) {
    if (targets.length === 0) return;
    setBusy(true);
    try {
      await api.acknowledgeCoverage(runId, targets, note);
      setNote("");
      await load();
      onChange?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not record that.");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    // Never silent. A panel that vanishes on a failed request tells the reviewer that
    // there was nothing to check, which is the one thing it must never imply.
    return (
      <Card className="mb-4" data-testid="coverage-card">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4" /> What was checked
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-3 text-xs">
          <p className="text-destructive">{error}</p>
          <Button variant="outline" size="xs" className="mt-2" onClick={() => void load()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (!coverage) return <Skeleton className="mb-4 h-12" data-testid="coverage-loading" />;
  if (coverage.reason) {
    return (
      <Card className="mb-4" data-testid="coverage-card">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4" /> What was checked
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-3 text-xs text-muted-foreground">{coverage.reason}</CardContent>
      </Card>
    );
  }

  const counts = coverage.counts;
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const gaps = coverage.requirements.filter(needsAcknowledging);
  const outstanding = coverage.outstanding;
  const emptyReports = coverage.reports.filter((report) => report.checks_applied === 0);

  return (
    <Card className="mb-4" data-testid="coverage-card">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4" /> What was checked
          {outstanding.length > 0 ? (
            <Badge tone="warn">{outstanding.length} to acknowledge</Badge>
          ) : (
            <Badge tone="success">nothing outstanding</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-3 text-xs">
        <p className="mb-2 text-muted-foreground">
          A finding says what disagreed. This says what was compared, and what was not: the absence
          of a finding is not on its own a pass. Counted by code.
        </p>

        <div className="mb-3 flex flex-wrap gap-3">
          {(Object.keys(STATE_LABEL) as CoverageState[]).map((state) => (
            <span key={state} className="flex items-center gap-1.5">
              <Badge tone={STATE_TONE[state]}>{counts[state] ?? 0}</Badge>
              <span className="text-muted-foreground">{STATE_LABEL[state]}</span>
            </span>
          ))}
          <span className="text-muted-foreground">of {total} requirements</span>
        </div>

        {coverage.notices.length > 0 ? (
          <div className="mb-3 rounded-md border border-warn/40 bg-warn/5 p-2">
            <b className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" /> Notices
            </b>
            <ul className="mt-1 space-y-0.5">
              {coverage.notices.map((notice) => (
                <li key={notice}>{notice}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {emptyReports.length > 0 ? (
          <p className="mb-3 rounded-md border border-warn/40 bg-warn/5 p-2">
            <b>No check examined</b>{" "}
            {emptyReports.map((report) => report.kind.replace(/_/g, " ")).join(", ")}. A report
            nobody asks anything of cannot disagree with anything.
          </p>
        ) : null}

        {gaps.length > 0 || coverage.unevaluated.length > 0 ? (
          <>
            <Button
              variant="ghost"
              size="xs"
              className="mb-2"
              onClick={() => setOpen((previous) => !previous)}
            >
              <Eye className="h-3.5 w-3.5" />
              {open ? "Hide" : "Show"} the {gaps.length + coverage.unevaluated.length} that nothing
              evidenced
            </Button>

            {open ? (
              <div className="space-y-1.5">
                {gaps.map((entry) => (
                  <div
                    key={entry.rule_id}
                    className="rounded-md border p-2"
                    data-testid="coverage-gap"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="mono text-muted-foreground">{entry.rule_id}</span>
                      <Badge tone={STATE_TONE[entry.state]}>{STATE_LABEL[entry.state]}</Badge>
                      {entry.osl_ref ? (
                        <span className="text-muted-foreground">{entry.osl_ref}</span>
                      ) : null}
                      {entry.acknowledged ? (
                        <Badge tone="success">acknowledged by {entry.acknowledged_by}</Badge>
                      ) : null}
                    </div>
                    <p className="mt-1">{entry.summary}</p>
                    <p className="mt-0.5 text-muted-foreground">{entry.reason}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {editable && !entry.acknowledged ? (
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={busy}
                          onClick={() => void acknowledge([entry.rule_id])}
                        >
                          I have seen this
                        </Button>
                      ) : null}
                      {onObserve ? (
                        <Button
                          size="xs"
                          variant="ghost"
                          title="Say what should have been checked here"
                          onClick={() => onObserve(entry)}
                          data-testid="gap-observe"
                        >
                          <Lightbulb className="h-3.5 w-3.5" /> What should this check?
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))}

                {coverage.unevaluated.map((entry) => (
                  <div key={entry.finding_id} className="rounded-md border p-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="mono text-muted-foreground">{entry.finding_id}</span>
                      <Badge tone="warn">Could not be evaluated</Badge>
                      {entry.acknowledged ? (
                        <Badge tone="success">acknowledged by {entry.acknowledged_by}</Badge>
                      ) : null}
                    </div>
                    <p className="mt-1">{entry.title}</p>
                    {editable && !entry.acknowledged ? (
                      <Button
                        size="xs"
                        variant="outline"
                        className="mt-1.5"
                        disabled={busy}
                        onClick={() => void acknowledge([entry.finding_id])}
                      >
                        I have seen this
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            {editable && outstanding.length > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Input
                  className="min-w-[14rem] flex-1"
                  placeholder="Note — why these are acceptable, or who you raised them with"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  aria-label="Acknowledgement note"
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void acknowledge(outstanding)}
                >
                  I have seen all {outstanding.length}
                </Button>
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground">
            Every requirement was either checked against a report or is already a finding of its
            own.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

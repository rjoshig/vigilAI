"use client";

/**
 * The usage dashboard: runs, durations, tokens, cache hits, and accuracy.
 *
 * Every number is plain SQL over the run tables (`docs/phase-4.md`). No derived tables
 * to keep in step, and no model call.
 */

import * as React from "react";

import { Explain } from "@/components/explain";
import { Sparkline } from "@/components/sparkline";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  PageHeader,
  Skeleton,
  Stat,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Usage } from "@/lib/types";
import { fmtDuration, fmtInt } from "@/lib/utils";

function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

export default function UsagePage() {
  const [usage, setUsage] = React.useState<Usage | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      setUsage(await api.getUsage());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!usage) return <Skeleton className="h-96" />;

  const byType = Object.entries(usage.findings_by_type).sort((a, b) => b[1] - a[1]);
  const peak = Math.max(...byType.map(([, count]) => count), 1);

  return (
    <>
      <PageHeader
        explain={
          <Explain label="Reading these numbers">
            What the tool has actually spent: calls, tokens and cache hits over time. Every number
            is counted by code from the run records.
            <br />
            <br />A high cache-hit rate is the thing to want — it means repeated content is costing
            nothing. The token budget that stops a runaway run is under <b>Settings &rarr; Model</b>
            .
          </Explain>
        }
        title="Usage"
        description="Tool health and cost. Every number comes from the run tables; no prompts or content are stored."
      />

      <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Runs" value={fmtInt(usage.runs_total)} />
        <Stat
          label="Duration p50 / p95"
          value={`${fmtDuration(usage.duration_p50_ms)} / ${fmtDuration(usage.duration_p95_ms)}`}
        />
        <Stat
          label="Failure rate"
          value={percent(usage.failure_rate)}
          tone={usage.failure_rate > 0 ? "destructive" : "muted"}
        />
        <Stat label="Tokens" value={fmtInt(usage.tokens_total)} />
        <Stat label="Cache hit rate" value={percent(usage.cache_hit_rate)} tone="success" />
        <Stat
          label="JSON failure rate"
          value={percent(usage.json_failure_rate)}
          hint="answers that did not validate"
        />
        <Stat
          label="False-positive rate"
          value={percent(usage.false_positive_rate)}
          hint="findings reviewers marked OK"
          tone="warn"
        />
        <Stat
          label="Decisions"
          value={fmtInt(Object.values(usage.decisions).reduce((a, b) => a + b, 0))}
          hint={Object.entries(usage.decisions)
            .filter(([status]) => status !== "undecided")
            .map(([status, count]) => `${count} ${status.replace("_", " ")}`)
            .join(" · ")}
        />
      </div>

      <div className="mb-4 grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Runs per day</CardTitle>
          </CardHeader>
          <CardContent>
            <Sparkline values={usage.runs_per_day} label="Runs per day" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Tokens per day</CardTitle>
          </CardHeader>
          <CardContent>
            <Sparkline values={usage.tokens_per_day} label="Tokens per day" tone="tertiary" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Findings by type</CardTitle>
        </CardHeader>
        <CardContent>
          {byType.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">No findings yet</p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {byType.map(([type, count]) => (
                <div
                  key={type}
                  className="grid grid-cols-[12rem_1fr_3rem] items-center gap-2 text-xs"
                >
                  <span>{type.replace(/_/g, " ")}</span>
                  <span className="h-2 overflow-hidden rounded-full bg-muted">
                    <span
                      className="block h-full rounded-full bg-primary"
                      style={{ width: `${(count / peak) * 100}%` }}
                    />
                  </span>
                  <span className="text-right tabular-nums text-muted-foreground">{count}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}

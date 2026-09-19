"use client";

/** Run stats: stage timings, model calls, tokens, and cache hits. */

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import {
  Badge,
  Card,
  ErrorState,
  PageHeader,
  Skeleton,
  Stat,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { STAGE_LABELS, type RunStats } from "@/lib/types";
import { fmtDuration, fmtInt } from "@/lib/utils";

/** Stages that call a model; the rest are pure code and should report zero calls. */
const LLM_STAGES = new Set(["s2_extract", "s3_describe", "s4_trace", "s8_verify", "s9_summarize"]);

export default function StatsPage() {
  const params = useParams<{ id: string }>();
  const runId = Number(params.id);
  const [stats, setStats] = React.useState<RunStats | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      setStats(await api.getStats(runId));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load the stats.");
    }
  }, [runId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!stats) return <Skeleton className="h-96" />;

  const cacheRate =
    stats.llm_calls > 0 ? `${Math.round((stats.cache_hits / stats.llm_calls) * 100)}%` : "—";

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/runs" className="hover:underline">
              Runs
            </Link>{" "}
            ›{" "}
            <Link href={`/runs/${runId}`} className="mono hover:underline">
              VR-{String(runId).padStart(4, "0")}
            </Link>
          </>
        }
        title="Run stats"
        description="Every stage records its status, duration, and token use, so a failed run resumes from the last good stage."
      />

      <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Pipeline duration" value={fmtDuration(stats.total_duration_ms)} />
        <Stat label="Model calls" value={fmtInt(stats.llm_calls)} />
        <Stat label="Cache hits" value={fmtInt(stats.cache_hits)} hint={cacheRate} tone="success" />
        <Stat label="Prompt tokens" value={fmtInt(stats.prompt_tokens)} />
        <Stat label="Completion tokens" value={fmtInt(stats.completion_tokens)} />
      </div>

      <Card className="p-0">
        <Table>
          <thead>
            <TR className="hover:bg-transparent">
              <TH>#</TH>
              <TH>Stage</TH>
              <TH>Kind</TH>
              <TH>Status</TH>
              <TH className="text-right">Duration</TH>
              <TH className="text-right">Calls</TH>
              <TH className="text-right">Cache hits</TH>
              <TH className="text-right">Tokens</TH>
            </TR>
          </thead>
          <tbody>
            {stats.stages.map((stage, index) => (
              <TR key={stage.stage}>
                <TD className="text-muted-foreground">{index + 1}</TD>
                <TD>{STAGE_LABELS[stage.stage] ?? stage.stage}</TD>
                <TD>
                  <Badge tone={LLM_STAGES.has(stage.stage) ? "info" : "muted"}>
                    {LLM_STAGES.has(stage.stage) ? "LLM" : "code"}
                  </Badge>
                </TD>
                <TD>
                  <Badge
                    tone={
                      stage.status === "done"
                        ? "success"
                        : stage.status === "failed"
                          ? "destructive"
                          : "muted"
                    }
                  >
                    {stage.status}
                  </Badge>
                </TD>
                <TD className="text-right tabular-nums">{fmtDuration(stage.duration_ms)}</TD>
                <TD className="text-right tabular-nums">{stage.llm_calls || "—"}</TD>
                <TD className="text-right tabular-nums text-success">{stage.cache_hits || "—"}</TD>
                <TD className="text-right tabular-nums">{fmtInt(stage.tokens)}</TD>
              </TR>
            ))}
          </tbody>
        </Table>
      </Card>

      <p className="mt-3 text-xs text-muted-foreground">
        Prompts and raw responses are not stored. These numbers are ids and counts only.
      </p>
    </>
  );
}

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

      <BudgetMeter stats={stats} />

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

/**
 * What this run spent, against the one hard limit in the tool (Phase 6.21d).
 *
 * The per-run token budget is the only thing that stops a run in the product, and
 * until this a person only learned about it by a run failing. Showing how close a run
 * came turns a refusal into something somebody could have seen arriving.
 *
 * Cost is shown only where an administrator has set a rate. A cost built on a rate
 * nobody supplied is a number that gets quoted back as fact, so its absence is stated
 * rather than shown as a zero.
 */
function BudgetMeter({ stats }: { stats: RunStats }) {
  const used = stats.prompt_tokens + stats.completion_tokens;
  const budget = stats.budget_tokens;
  if (budget <= 0) return null;

  const share = Math.min(used / budget, 1);
  const tight = share >= 0.8;
  const costed = stats.rate_per_million > 0;

  return (
    <Card className="mb-4 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">
          {fmtInt(used)} of {fmtInt(budget)} tokens
          {costed ? (
            <>
              {" "}
              ·{" "}
              <span className="tabular-nums">
                {stats.cost.toLocaleString(undefined, {
                  style: "currency",
                  currency: stats.currency,
                  maximumFractionDigits: 2,
                })}
              </span>
            </>
          ) : null}
        </p>
        <p className={tight ? "text-xs font-medium text-warn" : "text-xs text-muted-foreground"}>
          {Math.round(share * 100)}% of this run&rsquo;s budget
        </p>
      </div>
      <div
        className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={`${Math.round(share * 100)} percent of this run's token budget used`}
      >
        <div
          className={tight ? "h-full bg-warn" : "h-full bg-primary/70"}
          style={{ width: `${Math.max(share * 100, 1)}%` }}
        />
      </div>
      <p className="mt-2 text-[0.7rem] text-muted-foreground">
        A run that reaches its budget stops and says so; nothing else in the tool refuses anything
        over cost.{" "}
        {stats.cache_hits > 0
          ? `${fmtInt(stats.cache_hits)} call${stats.cache_hits === 1 ? "" : "s"} came from the cache and cost nothing.`
          : ""}
      </p>
    </Card>
  );
}

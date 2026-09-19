"use client";

/**
 * The Runs list: history, filters, queue position, and live stage progress.
 *
 * Polls every three seconds while any run is queued or running, and stops when none
 * is (`docs/design.md` "API endpoints"). Polling a finished list forever would be
 * pointless load on a machine that is also serving the worker.
 */

import { Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Stat,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { STATUS_LABEL, STATUS_TONE, isActive } from "@/lib/display";
import { STAGE_LABELS, type RunSummary } from "@/lib/types";
import { fmtRelative } from "@/lib/utils";

/** How often to re-read the list while something is moving. */
const POLL_MS = 3000;

/**
 * What the Progress column shows, which depends entirely on where the run is.
 *
 * The list endpoint does not carry per-stage records — it would be a join per row for
 * a column most rows do not need — so a finished run reports its outcome rather than
 * an empty progress bar, which is what it used to show.
 */
function RunProgress({ run }: { run: RunSummary }) {
  if (run.status === "queued") {
    return (
      <span className="text-xs text-muted-foreground">
        Queue position <b>#{run.queue_position ?? "?"}</b>
      </span>
    );
  }
  if (run.status === "running") {
    return (
      <span className="text-xs text-info">
        {run.current_stage ? (STAGE_LABELS[run.current_stage] ?? run.current_stage) : "Starting…"}
      </span>
    );
  }
  if (run.status === "failed") {
    // The stored error already names the stage it failed at, so prefixing it again
    // produced "Failed at s1_parse: PipelineError: s1_parse: …".
    return <span className="text-xs text-destructive">{run.error || "Failed"}</span>;
  }
  if (run.status === "draft") {
    return <span className="text-xs text-muted-foreground">Draft — no files uploaded yet</span>;
  }

  const total = run.high + run.medium + run.low + run.review;
  const finished = run.finished_at ? fmtRelative(run.finished_at) : "";
  return (
    <span className="text-xs text-muted-foreground">
      {run.status === "finalized" ? "Report frozen" : "Pipeline complete"}
      {finished ? ` ${finished}` : ""} ·{" "}
      {total === 0 ? "no findings" : `${total} finding${total === 1 ? "" : "s"}`}
    </span>
  );
}

export default function RunsPage() {
  const [runs, setRuns] = React.useState<RunSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setRuns(await api.listRuns({ status: status || undefined, limit: 100 }));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [status]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const anyActive = (runs ?? []).some((run) => isActive(run.status));
  React.useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyActive, load]);

  const visible = (runs ?? []).filter((run) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [run.customer_name, run.order_number, run.configuration_id, String(run.id)]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });

  const counts = {
    queued: (runs ?? []).filter((r) => r.status === "queued").length,
    running: (runs ?? []).filter((r) => r.status === "running").length,
    review: (runs ?? []).filter((r) => r.status === "needs_review").length,
    failed: (runs ?? []).filter((r) => r.status === "failed").length,
  };

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every QC validation run: queue position, live stage progress, and findings once the pipeline finishes."
        action={
          <>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
            <Link href="/runs/new">
              <Button>
                <Plus className="h-4 w-4" /> New run
              </Button>
            </Link>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Total runs" value={runs?.length ?? "—"} />
        <Stat label="Queued / running" value={`${counts.queued} / ${counts.running}`} tone="info" />
        <Stat label="Needs review" value={counts.review} tone="warn" />
        <Stat label="Failed" value={counts.failed} tone={counts.failed ? "destructive" : "muted"} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="max-w-xs"
          placeholder="Search run, customer, order, configuration…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search runs"
        />
        <Select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="needs_review">Needs review</option>
          <option value="finalized">Finalized</option>
          <option value="failed">Failed</option>
        </Select>
        {anyActive ? (
          <span className="text-xs text-muted-foreground">Updating every 3 seconds…</span>
        ) : null}
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {!runs && !error ? <Skeleton className="h-64" /> : null}

      {runs && !error ? (
        <Card className="p-0">
          {visible.length === 0 ? (
            <EmptyState
              title="No runs yet"
              hint="Submit an OSL, a config, and at least one report to start one."
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH>Run</TH>
                  <TH>Customer</TH>
                  <TH>Order</TH>
                  <TH>Configuration</TH>
                  <TH>Submitted</TH>
                  <TH>Submitted by</TH>
                  <TH>Status</TH>
                  <TH className="min-w-[13rem]">Progress</TH>
                  <TH className="text-center">H / M / L</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </thead>
              <tbody>
                {visible.map((run) => (
                  <TR key={run.id}>
                    <TD className="mono">VR-{String(run.id).padStart(4, "0")}</TD>
                    <TD>{run.customer_name}</TD>
                    <TD className="mono">{run.order_number}</TD>
                    <TD className="mono text-xs">{run.configuration_id}</TD>
                    <TD className="text-xs text-muted-foreground">{fmtRelative(run.created_at)}</TD>
                    <TD className="whitespace-nowrap text-xs">{run.submitted_by || "—"}</TD>
                    <TD>
                      <Badge tone={STATUS_TONE[run.status]}>{STATUS_LABEL[run.status]}</Badge>
                    </TD>
                    <TD>
                      <RunProgress run={run} />
                    </TD>
                    <TD className="whitespace-nowrap text-center tabular-nums">
                      {run.high + run.medium + run.low === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <>
                          <span className="text-destructive">{run.high}</span> /{" "}
                          <span className="text-warn">{run.medium}</span> /{" "}
                          <span className="text-info">{run.low}</span>
                        </>
                      )}
                    </TD>
                    <TD className="text-right">
                      <Link href={`/runs/${run.id}`}>
                        <Button
                          size="sm"
                          variant={run.status === "needs_review" ? "default" : "outline"}
                        >
                          {run.status === "needs_review" ? "Review" : "Open"}
                        </Button>
                      </Link>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : null}
    </>
  );
}

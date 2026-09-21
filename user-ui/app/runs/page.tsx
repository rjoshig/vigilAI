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
import { expiresIn } from "@/lib/draft";
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
    // The list shows the stage and the first few words; the run page carries the whole
    // message, so a long traceback never stretches a row.
    const message = run.error || "Failed";
    const brief =
      message.length > ERROR_PREVIEW_CHARS ? `${message.slice(0, ERROR_PREVIEW_CHARS)}…` : message;
    return (
      <span className="text-xs text-destructive" title={message}>
        Failed{run.current_stage ? ` at ${run.current_stage}` : ""} · {brief}
      </span>
    );
  }
  if (run.status === "draft") {
    const left = expiresIn(run.expires_at);
    return (
      <span className="text-xs text-muted-foreground">
        Draft — not submitted{left ? ` · ${left}` : ""}
      </span>
    );
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

/** How much of a failure message the list shows; the run page shows it all. */
const ERROR_PREVIEW_CHARS = 40;

export default function RunsPage() {
  const [runs, setRuns] = React.useState<RunSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [submitter, setSubmitter] = React.useState("");
  // Who the admin console asked for, when it linked here. Read from the query string
  // on the client rather than with `useSearchParams`, which would put this whole page
  // behind a Suspense boundary for a parameter that is usually absent.
  const [submittedBy, setSubmittedBy] = React.useState<number | null>(null);
  // Fetched separately because the list deliberately does not carry drafts. They are
  // few by nature — one per source run per person, and they expire in days — so this
  // is a small request, and it is what lets the toggle show a count.
  const [draftCount, setDraftCount] = React.useState(0);

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const who = Number(params.get("submitted_by"));
    if (Number.isInteger(who) && who > 0) setSubmittedBy(who);
    const wanted = params.get("status");
    if (wanted) setStatus(wanted);
  }, []);

  const load = React.useCallback(async () => {
    try {
      setRuns(
        await api.listRuns({
          status: status || undefined,
          submittedBy: submittedBy ?? undefined,
          limit: 100,
        })
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
    try {
      setDraftCount(
        (await api.listRuns({ status: "draft", submittedBy: submittedBy ?? undefined, limit: 100 }))
          .length
      );
    } catch {
      // A count is decoration: failing to read it must not empty the runs list above.
      setDraftCount(0);
    }
  }, [status, submittedBy]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const anyActive = (runs ?? []).some((run) => isActive(run.status));
  React.useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyActive, load]);

  // Everybody who appears in what was loaded, for the picker. Built from the runs
  // themselves rather than from the accounts list: a person with no runs in view is not
  // a filter anybody wants, and the user app has no business listing accounts.
  const submitters = Array.from(
    new Set((runs ?? []).map((run) => run.submitted_by).filter((name) => name))
  ).sort((left, right) => left.localeCompare(right));

  const visible = (runs ?? []).filter((run) => {
    if (submitter && run.submitted_by !== submitter) return false;
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [
      run.customer_name,
      run.order_number,
      run.configuration_id,
      run.submitted_by,
      String(run.id),
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });

  // A lifetime total only ever grows, so it stops being a number anybody reads.
  // Thirty days is the window a team actually works in.
  const thirtyDaysAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;
  const recentCount = runs
    ? runs.filter((r) => new Date(r.created_at).getTime() >= thirtyDaysAgo).length
    : null;

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
        <Stat label="Runs, last 30 days" value={recentCount ?? "—"} />
        <Stat label="Queued / running" value={`${counts.queued} / ${counts.running}`} tone="info" />
        <Stat label="Needs review" value={counts.review} tone="warn" />
        <Stat label="Failed" value={counts.failed} tone={counts.failed ? "destructive" : "muted"} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="max-w-xs"
          placeholder="Search run, customer, order, configuration, who submitted…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search runs"
        />
        <Select
          value={submitter}
          onChange={(event) => setSubmitter(event.target.value)}
          aria-label="Filter by who submitted the run"
          disabled={submittedBy !== null}
        >
          <option value="">Anyone</option>
          {submitters.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
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
        {/* Drafts are unfinished work, not deliveries, so they are kept out of the
            history and reached by this one toggle instead (Phase 6.23c). */}
        <Button
          variant={status === "draft" ? "default" : "outline"}
          size="sm"
          onClick={() => setStatus(status === "draft" ? "" : "draft")}
          aria-pressed={status === "draft"}
          title={
            status === "draft"
              ? "Back to the runs"
              : "Runs you cloned and have not submitted yet. They are kept out of the list below."
          }
        >
          {status === "draft" ? "Back to runs" : `Drafts${draftCount ? ` (${draftCount})` : ""}`}
        </Button>
        {submittedBy !== null ? (
          <span className="inline-flex items-center gap-1 rounded-md border border-info/40 bg-info/10 px-2 py-1 text-xs">
            Showing one person&rsquo;s runs
            <Button
              variant="ghost"
              size="xs"
              onClick={() => {
                setSubmittedBy(null);
                window.history.replaceState(null, "", "/runs");
              }}
            >
              Show everyone
            </Button>
          </span>
        ) : null}
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
              title={status === "draft" ? "No drafts" : "No runs yet"}
              hint={
                status === "draft"
                  ? "Cloning a finished run leaves a draft here until you submit it."
                  : "Submit an OSL, a config, and at least one report to start one."
              }
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH>Run</TH>
                  <TH>Customer</TH>
                  <TH>Delivery programme</TH>
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
                    <TD className="text-xs">
                      {run.scope_label || run.scope ? (
                        <Badge tone="muted">{run.scope_label || run.scope}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD className="mono">{run.order_number}</TD>
                    <TD className="text-xs">
                      <div className="mono">{run.configuration_id}</div>
                      <div className="text-[0.7rem] text-muted-foreground">
                        credit {run.credit_date ?? "—"} · run {run.created_at.slice(0, 10)}
                      </div>
                    </TD>
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
                      <Link
                        href={
                          run.status === "draft" ? `/runs/new?draft=${run.id}` : `/runs/${run.id}`
                        }
                      >
                        <Button
                          size="sm"
                          variant={run.status === "needs_review" ? "default" : "outline"}
                        >
                          {run.status === "needs_review"
                            ? "Review"
                            : run.status === "draft"
                              ? "Finish"
                              : "Open"}
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

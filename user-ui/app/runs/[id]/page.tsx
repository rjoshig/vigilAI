"use client";

/**
 * The Review screen: the traceability matrix, the findings, and the decisions.
 *
 * While the run is still queued or running this shows live stage progress instead, and
 * polls every three seconds until the pipeline finishes.
 */

import { BarChart3, CheckCircle2, Copy, RefreshCw, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { EvidencePanel } from "@/components/evidence-panel";
import { StageProgress } from "@/components/stage-progress";
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
  Select,
  Skeleton,
  Stat,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import {
  FINDING_LABEL,
  LEG_LABEL,
  MATRIX_TONE,
  SEVERITY_LABEL,
  SEVERITY_ORDER,
  SEVERITY_TONE,
  STATUS_LABEL,
  STATUS_TONE,
  isActive,
  isOk,
} from "@/lib/display";
import { buildMatrix, countByStatus, ruleValues, type MatrixRow } from "@/lib/matrix";
import type { Finding, Requirements, RunDetail, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

type Tab = "matrix" | "findings";

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const runId = Number(params.id);

  const [run, setRun] = React.useState<RunDetail | null>(null);
  const [requirements, setRequirements] = React.useState<Requirements | null>(null);
  const [findings, setFindings] = React.useState<Finding[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<Tab>("matrix");
  const [openFinding, setOpenFinding] = React.useState<Finding | null>(null);
  const [busy, setBusy] = React.useState(false);

  const loadRun = React.useCallback(async () => {
    try {
      setRun(await api.getRun(runId));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [runId]);

  const loadReview = React.useCallback(async () => {
    try {
      const [nextRequirements, nextFindings] = await Promise.all([
        api.getRequirements(runId),
        api.listFindings(runId),
      ]);
      setRequirements(nextRequirements);
      setFindings(nextFindings);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load the review data.");
    }
  }, [runId]);

  React.useEffect(() => {
    void loadRun();
  }, [loadRun]);

  const active = run ? isActive(run.status) : false;
  React.useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void loadRun(), POLL_MS);
    return () => clearInterval(timer);
  }, [active, loadRun]);

  const ready = run !== null && !isActive(run.status) && run.status !== "draft";
  React.useEffect(() => {
    if (ready) void loadReview();
  }, [ready, loadReview]);

  async function decide(finding: Finding, ok: boolean, note: string) {
    setBusy(true);
    try {
      const updated = await api.reviewFinding(
        finding.id,
        ok ? "false_positive" : "confirmed",
        note
      );
      setFindings((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));
      setOpenFinding((prev) => (prev && prev.id === updated.id ? updated : prev));
      await loadRun();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not record the decision.");
    } finally {
      setBusy(false);
    }
  }

  async function bulkOk() {
    setBusy(true);
    try {
      await api.bulkOkLow(runId);
      await Promise.all([loadReview(), loadRun()]);
    } finally {
      setBusy(false);
    }
  }

  async function recheck() {
    setBusy(true);
    try {
      await api.recheck(runId);
      await loadRun();
    } finally {
      setBusy(false);
    }
  }

  async function clone() {
    const result = await api.cloneRun(runId);
    router.push(`/runs/${result.run_id}`);
  }

  if (error && !run) return <ErrorState message={error} onRetry={() => void loadRun()} />;
  if (!run) return <Skeleton className="h-96" />;

  const rows = requirements ? buildMatrix(requirements, findings) : [];
  const undecidedHigh = findings.filter(
    (f) => f.severity === "high" && f.review_status === "undecided"
  ).length;

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/runs" className="hover:underline">
              Runs
            </Link>{" "}
            › <span className="mono">VR-{String(run.id).padStart(4, "0")}</span>
          </>
        }
        title={`${run.customer_name} · ${run.order_number}`}
        description={`Configuration ${run.configuration_id}${
          run.model_used ? ` · model ${run.model_used} · prompts v${run.prompt_version}` : ""
        }${run.rules_version > 1 ? ` · rules v${run.rules_version}` : ""}`}
        action={
          <>
            <Badge tone={STATUS_TONE[run.status]}>{STATUS_LABEL[run.status]}</Badge>
            <Link href={`/runs/${run.id}/stats`}>
              <Button variant="outline" size="sm">
                <BarChart3 className="h-4 w-4" /> Run stats
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || active}
              onClick={() => void recheck()}
            >
              <RefreshCw className="h-4 w-4" /> Re-check
            </Button>
            <Button variant="outline" size="sm" onClick={() => void clone()}>
              <Copy className="h-4 w-4" /> Clone
            </Button>
          </>
        }
      />

      {run.status === "failed" ? (
        <div className="mb-4">
          <ErrorState message={`The run failed at ${run.current_stage}: ${run.error}`} />
        </div>
      ) : null}

      {active ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {run.status === "queued"
                ? `Queued · position #${run.queue_position ?? "?"}`
                : "Running"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <StageProgress stages={run.stages} currentStage={run.current_stage} />
            <p className="mt-3 text-xs text-muted-foreground">
              Updating every 3 seconds. The review screen opens when the pipeline finishes.
            </p>
          </CardContent>
        </Card>
      ) : null}

      {ready ? (
        <>
          <div className="mb-4 rounded-md border border-info/40 bg-info/5 p-3 text-xs">
            <b>
              {undecidedHigh === 0
                ? "Every high-severity finding has a decision."
                : `${undecidedHigh} high-severity finding${undecidedHigh === 1 ? "" : "s"} still need a decision.`}
            </b>{" "}
            The final report can only be generated once they all do. Low-severity findings can be
            decided in bulk. Review decisions never call the model.
          </div>

          <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-5">
            <Stat label="Requirements" value={requirements?.rules.length ?? "—"} />
            {SEVERITY_ORDER.map((severity) => (
              <Stat
                key={severity}
                label={SEVERITY_LABEL[severity]}
                value={findings.filter((f) => f.severity === severity).length}
                hint={`${
                  findings.filter((f) => f.severity === severity && f.review_status !== "undecided")
                    .length
                } decided`}
                tone={severity === "high" ? "destructive" : severity === "medium" ? "warn" : "info"}
              />
            ))}
          </div>

          {run.summary ? (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle>AI summary</CardTitle>
              </CardHeader>
              <CardContent className="text-xs leading-relaxed">{run.summary}</CardContent>
            </Card>
          ) : null}

          <div className="mb-4 flex gap-1 border-b">
            {(["matrix", "findings"] as Tab[]).map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setTab(name)}
                className={cn(
                  "-mb-px border-b-2 px-3.5 py-2 text-sm font-medium",
                  tab === name
                    ? "border-primary font-semibold text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {name === "matrix" ? "Traceability matrix" : `Findings (${findings.length})`}
              </button>
            ))}
          </div>

          {tab === "matrix" ? (
            <MatrixTab rows={rows} onOpen={setOpenFinding} />
          ) : (
            <FindingsTab
              findings={findings}
              busy={busy}
              onDecide={decide}
              onBulkOk={() => void bulkOk()}
              onOpen={setOpenFinding}
            />
          )}
        </>
      ) : null}

      <EvidencePanel finding={openFinding} onClose={() => setOpenFinding(null)} />
    </>
  );
}

function MatrixTab({ rows, onOpen }: { rows: MatrixRow[]; onOpen: (f: Finding) => void }) {
  const [filter, setFilter] = React.useState<string>("all");
  const counts = countByStatus(rows);
  const visible = filter === "all" ? rows : rows.filter((row) => row.status === filter);

  if (rows.length === 0) return <EmptyState title="No requirements were extracted." />;

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <FilterChip
          label={`All ${rows.length}`}
          on={filter === "all"}
          onClick={() => setFilter("all")}
        />
        {(Object.keys(counts) as (keyof typeof counts)[])
          .filter((status) => counts[status] > 0)
          .map((status) => (
            <FilterChip
              key={status}
              label={`${status} ${counts[status]}`}
              on={filter === status}
              onClick={() => setFilter(status)}
            />
          ))}
        <span className="ml-auto text-xs text-muted-foreground">
          One row per OSL requirement. Code compared every value.
        </span>
      </div>

      <Card className="p-0">
        <Table>
          <thead>
            <TR className="hover:bg-transparent">
              <TH>Req</TH>
              <TH>Type</TH>
              <TH className="min-w-[14rem]">OSL (source of truth)</TH>
              <TH className="min-w-[12rem]">Config</TH>
              <TH>Status</TH>
              <TH>Conf.</TH>
              <TH>Findings</TH>
            </TR>
          </thead>
          <tbody>
            {visible.map((row) => (
              <TR key={row.rule.rule_id}>
                <TD className="mono">{row.rule.rule_id}</TD>
                <TD>
                  <Badge tone="outline">{row.rule.req_type}</Badge>
                </TD>
                <TD className="text-xs">{ruleValues(row.rule)}</TD>
                <TD className="text-xs">
                  {row.element ? (
                    <>
                      <span className="mono text-muted-foreground">{row.element.json_path}</span>
                      {row.trace?.by_code ? (
                        <span className="ml-1 text-[0.65rem] text-muted-foreground">
                          (linked by code)
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-destructive">No matching config rule</span>
                  )}
                </TD>
                <TD>
                  <Badge tone={MATRIX_TONE[row.status]}>{row.status}</Badge>
                </TD>
                <TD className="text-xs tabular-nums">{row.rule.confidence.toFixed(2)}</TD>
                <TD>
                  {row.findings.length === 0 ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {row.findings.map((finding) => (
                        <button
                          key={finding.id}
                          type="button"
                          onClick={() => onOpen(finding)}
                          className="rounded-full bg-muted px-2 py-0.5 text-[0.65rem] font-semibold hover:bg-accent"
                        >
                          {finding.finding_id}
                        </button>
                      ))}
                    </div>
                  )}
                </TD>
              </TR>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}

function FilterChip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs font-medium capitalize",
        on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"
      )}
    >
      {label}
    </button>
  );
}

interface FindingsTabProps {
  findings: Finding[];
  busy: boolean;
  onDecide: (finding: Finding, ok: boolean, note: string) => Promise<void>;
  onBulkOk: () => void;
  onOpen: (finding: Finding) => void;
}

function FindingsTab({ findings, busy, onDecide, onBulkOk, onOpen }: FindingsTabProps) {
  const [severity, setSeverity] = React.useState<Severity | "all">("all");
  const [search, setSearch] = React.useState("");

  const visible = findings.filter((finding) => {
    if (severity !== "all" && finding.severity !== severity) return false;
    const needle = search.trim().toLowerCase();
    return !needle || `${finding.title} ${finding.detail}`.toLowerCase().includes(needle);
  });

  if (findings.length === 0) {
    return <EmptyState title="No findings" hint="Every requirement was traced and matched." />;
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          value={severity}
          onChange={(event) => setSeverity(event.target.value as Severity | "all")}
          aria-label="Filter by severity"
        >
          <option value="all">All severities</option>
          {SEVERITY_ORDER.map((value) => (
            <option key={value} value={value}>
              {SEVERITY_LABEL[value]}
            </option>
          ))}
        </Select>
        <Input
          className="max-w-xs"
          placeholder="Search findings…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search findings"
        />
        <Button variant="outline" size="sm" className="ml-auto" disabled={busy} onClick={onBulkOk}>
          <CheckCircle2 className="h-4 w-4" /> Mark all low OK
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        {visible.map((finding) => (
          <FindingCard
            key={finding.id}
            finding={finding}
            busy={busy}
            onDecide={onDecide}
            onOpen={onOpen}
          />
        ))}
      </div>
    </>
  );
}

function FindingCard({
  finding,
  busy,
  onDecide,
  onOpen,
}: {
  finding: Finding;
  busy: boolean;
  onDecide: (finding: Finding, ok: boolean, note: string) => Promise<void>;
  onOpen: (finding: Finding) => void;
}) {
  const [note, setNote] = React.useState(finding.review_note);
  const decided = finding.review_status !== "undecided";
  const ok = isOk(finding.review_status);

  return (
    <Card
      className={cn(
        "cursor-pointer p-3.5 transition-colors hover:border-primary/50",
        decided && (ok ? "border-l-4 border-l-success" : "border-l-4 border-l-destructive")
      )}
      onClick={() => onOpen(finding)}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="mono text-xs text-muted-foreground">{finding.finding_id}</span>
        <Badge tone={SEVERITY_TONE[finding.severity]}>{SEVERITY_LABEL[finding.severity]}</Badge>
        <Badge tone="outline">{FINDING_LABEL[finding.type] ?? finding.type}</Badge>
        <span className="text-[0.68rem] font-semibold uppercase tracking-wide text-muted-foreground">
          {LEG_LABEL[finding.leg] ?? finding.leg}
        </span>
        <span className="min-w-[12rem] flex-1 text-sm font-semibold">{finding.title}</span>
        <Badge tone={decided ? (ok ? "solid-success" : "solid-destructive") : "muted"}>
          {decided ? (ok ? "OK" : "Not OK") : "undecided"}
        </Badge>
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{finding.detail}</p>

      <div
        className="mt-2.5 flex flex-wrap items-center gap-2"
        onClick={(event) => event.stopPropagation()}
      >
        <Button
          size="sm"
          variant={decided && ok ? "success" : "outline"}
          disabled={busy}
          onClick={() => void onDecide(finding, true, note)}
        >
          <CheckCircle2 className="h-4 w-4" /> OK
        </Button>
        <Button
          size="sm"
          variant={decided && !ok ? "destructive" : "outline"}
          disabled={busy}
          onClick={() => void onDecide(finding, false, note)}
        >
          <XCircle className="h-4 w-4" /> Not OK
        </Button>
        <Input
          className="min-w-[12rem] flex-1"
          placeholder="Comment — shown in the final report for Not OK items"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          aria-label={`Comment on ${finding.finding_id}`}
        />
      </div>
    </Card>
  );
}

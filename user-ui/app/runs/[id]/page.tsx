"use client";

/**
 * The Review screen: the traceability matrix, the findings, and the decisions.
 *
 * While the run is still queued or running this shows live stage progress instead, and
 * polls every three seconds until the pipeline finishes.
 */

import {
  BarChart3,
  CheckCircle2,
  Copy,
  FileText,
  Lightbulb,
  Lock,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { CoverageCard } from "@/components/coverage-card";
import { DriftCard } from "@/components/drift-card";
import { EvidencePanel } from "@/components/evidence-panel";
import { ObservationDialog, anchorOf, useTrainingEnabled } from "@/components/observation-dialog";
import { StageProgress } from "@/components/stage-progress";
import { TrainAiTag } from "@/components/train-ai-tag";
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
  decisionProblem,
  isActive,
  isOk,
} from "@/lib/display";
import { buildMatrix, countByStatus, ruleValues, type MatrixRow } from "@/lib/matrix";
import type { Anchor, Finding, Requirements, ReviewStatus, RunDetail, Severity } from "@/lib/types";
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
  // Nothing about training is drawn while this is false, which is the shipped default.
  const trainingEnabled = useTrainingEnabled();
  const [observing, setObserving] = React.useState<ObservationTarget | null>(null);

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

  async function decide(finding: Finding, status: ReviewStatus, note: string) {
    setBusy(true);
    try {
      const updated = await api.reviewFinding(finding.id, status, note);
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
        description={`Configuration ${run.configuration_id} · credit date ${
          run.credit_date ?? "—"
        } · run date ${run.created_at.slice(0, 10)}${
          run.submitted_by ? ` · submitted by ${run.submitted_by}` : ""
        }${
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
            {trainingEnabled ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setObserving({
                    anchors: [
                      anchorOf("osl_section", {
                        reference: `run:${run.id}`,
                        value: `${run.customer_name} · ${run.order_number}`,
                      }),
                    ],
                    context: `This run — ${run.customer_name} · ${run.order_number}`,
                    findingId: null,
                  })
                }
              >
                <Lightbulb className="h-4 w-4" /> What should this check?
                <TrainAiTag />
              </Button>
            ) : null}
            <Button variant="outline" size="sm" onClick={() => void clone()}>
              <Copy className="h-4 w-4" /> Clone
            </Button>
            <Link href={`/runs/${run.id}/report`}>
              <Button
                size="sm"
                disabled={!run.finalized && !run.can_finalize}
                title={
                  run.finalized
                    ? "Open the frozen report"
                    : run.can_finalize
                      ? "Every high-severity finding has a decision"
                      : "Decide every high-severity finding first"
                }
              >
                {run.finalized ? (
                  <>
                    <FileText className="h-4 w-4" /> Final report
                  </>
                ) : (
                  <>
                    <Lock className="h-4 w-4" /> Generate final report
                  </>
                )}
              </Button>
            </Link>
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

      {ready && run.config_notes.length > 0 ? (
        <Card className="mb-4">
          <CardHeader className="border-b">
            <CardTitle>Configuration notes given to the model</CardTitle>
          </CardHeader>
          <CardContent className="pt-3 text-xs">
            <p className="mb-2 text-muted-foreground">
              Standing notes on configuration <span className="mono">{run.configuration_id}</span>{" "}
              that were in force when this run was submitted. The model saw them as background,
              never as a requirement.
            </p>
            <ul className="list-disc space-y-1 pl-4">
              {run.config_notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {ready && run.configuration_id ? <DriftCard runId={runId} /> : null}

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

          <CoverageCard runId={runId} onChange={() => void loadRun()} editable={!run.finalized} />

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
              onObserve={trainingEnabled ? setObserving : null}
            />
          )}
        </>
      ) : null}

      <EvidencePanel finding={openFinding} onClose={() => setOpenFinding(null)} />

      {observing ? (
        <ObservationDialog
          anchors={observing.anchors}
          context={observing.context}
          runId={run.id}
          findingId={observing.findingId}
          onClose={() => setObserving(null)}
        />
      ) : null}
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

/** What an observation raised from this screen points at. */
interface ObservationTarget {
  anchors: Anchor[];
  context: string;
  findingId: number | null;
}

/**
 * The anchor for an observation raised from a finding.
 *
 * Raising one here is the most valuable path in the loop, because it turns a
 * dismissal into training input rather than a note nobody reads again.
 */
function findingTarget(finding: Finding): ObservationTarget {
  const evidence = finding.evidence ?? {};
  const anchors: Anchor[] = [
    anchorOf("finding", { reference: finding.finding_id, value: finding.title }),
  ];
  if (evidence.report_name || evidence.report_cell) {
    anchors.push(
      anchorOf("report_cell", {
        artifact: evidence.report_name ?? "",
        sheet: evidence.report_sheet ?? "",
        cell: evidence.report_cell ?? "",
        value: evidence.report_value ?? "",
      })
    );
  }
  if (evidence.config_path) {
    anchors.push(
      anchorOf("config_path", {
        reference: evidence.config_path,
        value: evidence.config_value ?? "",
      })
    );
  }
  if (evidence.osl_ref) {
    anchors.push(anchorOf("osl_section", { reference: evidence.osl_ref }));
  }
  return {
    anchors,
    context: `${finding.finding_id} — ${finding.title}`,
    findingId: finding.id,
  };
}

interface FindingsTabProps {
  findings: Finding[];
  busy: boolean;
  onDecide: (finding: Finding, status: ReviewStatus, note: string) => Promise<void>;
  onBulkOk: () => void;
  onOpen: (finding: Finding) => void;
  /** Null when Train AI mode is off, which removes the control entirely. */
  onObserve: ((target: ObservationTarget) => void) | null;
}

function FindingsTab({ findings, busy, onDecide, onBulkOk, onOpen, onObserve }: FindingsTabProps) {
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
            onObserve={onObserve}
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
  onObserve,
}: {
  finding: Finding;
  busy: boolean;
  onDecide: (finding: Finding, status: ReviewStatus, note: string) => Promise<void>;
  onOpen: (finding: Finding) => void;
  onObserve: ((target: ObservationTarget) => void) | null;
}) {
  const [note, setNote] = React.useState(finding.review_note);
  const [problem, setProblem] = React.useState("");
  const decided = finding.review_status !== "undecided";
  const ok = isOk(finding.review_status);

  /**
   * Record a decision, or say what is missing first.
   *
   * The API refuses the same cases; asking here means the reviewer never loses what
   * they typed to a rejection.
   */
  async function record(status: ReviewStatus) {
    const missing = decisionProblem(finding.severity, status, note);
    setProblem(missing);
    if (!missing) await onDecide(finding, status, note);
  }

  return (
    <Card
      data-testid="finding-card"
      data-severity={finding.severity}
      data-finding={finding.finding_id}
      data-review-status={finding.review_status}
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
          variant={finding.review_status === "false_positive" ? "success" : "outline"}
          disabled={busy}
          title="The finding is not a real problem"
          onClick={() => void record("false_positive")}
        >
          <CheckCircle2 className="h-4 w-4" /> False positive
        </Button>
        <Button
          size="sm"
          variant={finding.review_status === "accepted_risk" ? "success" : "outline"}
          disabled={busy}
          title="The finding is real and the delivery goes ahead anyway. Say why."
          onClick={() => void record("accepted_risk")}
        >
          <ShieldCheck className="h-4 w-4" /> Accepted risk
        </Button>
        <Button
          size="sm"
          variant={decided && !ok ? "destructive" : "outline"}
          disabled={busy}
          title="The delivery has to change"
          onClick={() => void record("confirmed")}
        >
          <XCircle className="h-4 w-4" /> Not OK
        </Button>
        <Input
          className="min-w-[12rem] flex-1"
          placeholder="Comment — shown in the final report for Not OK items"
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            setProblem("");
          }}
          aria-label={`Comment on ${finding.finding_id}`}
        />
        {onObserve ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onObserve(findingTarget(finding))}
            title="Turn what you know into something the tool can check"
          >
            <Lightbulb className="h-4 w-4" /> What should this check?
            <TrainAiTag />
          </Button>
        ) : null}
      </div>

      {problem ? (
        <p role="alert" className="mt-2 text-xs font-medium text-destructive">
          {problem}
        </p>
      ) : null}
    </Card>
  );
}

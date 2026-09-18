"use client";

/**
 * New run: the upload form and the duplicate-inputs dialog.
 *
 * The server decides what counts as a duplicate, because only it knows the input
 * fingerprint and which checks are active. The form's job is to ask for a reason when
 * the server says the inputs were already run (`docs/design.md` "LLM cost controls").
 */

import { AlertTriangle, Play, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { FileDrop } from "@/components/file-drop";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  Textarea,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { REPORT_KINDS, REPORT_LABELS, type DuplicateRun, type ReportKind } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

/** The report slots offered on the form; the rest are rare and accepted by the API. */
const OFFERED: ReportKind[] = [
  "dirt",
  "state_distribution",
  "field_distribution",
  "counts",
  "billing",
];

export default function NewRunPage() {
  const router = useRouter();

  const [customer, setCustomer] = React.useState("");
  const [order, setOrder] = React.useState("");
  const [configurationId, setConfigurationId] = React.useState("");
  const [runDate, setRunDate] = React.useState("");
  const [notes, setNotes] = React.useState("");

  const [osl, setOsl] = React.useState<File | null>(null);
  const [config, setConfig] = React.useState<File | null>(null);
  const [reports, setReports] = React.useState<Partial<Record<ReportKind, File | null>>>({});

  const [duplicate, setDuplicate] = React.useState<DuplicateRun | null>(null);
  const [rerunReason, setRerunReason] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const reportCount = OFFERED.filter((kind) => reports[kind]).length;
  const ready =
    Boolean(customer.trim() && order.trim() && configurationId.trim() && osl && config) &&
    reportCount > 0;

  function buildForm(reason: string): FormData {
    const form = new FormData();
    form.set("customer_name", customer.trim());
    form.set("order_number", order.trim());
    form.set("configuration_id", configurationId.trim());
    form.set("notes", notes);
    if (runDate) form.set("run_date", runDate);
    if (reason) form.set("rerun_reason", reason);
    if (osl) form.set("osl", osl);
    if (config) form.set("config", config);
    for (const kind of REPORT_KINDS) {
      const file = reports[kind];
      if (file) form.set(kind, file);
    }
    return form;
  }

  async function submit(reason: string) {
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.createRun(buildForm(reason));
      if (result.duplicate) {
        setDuplicate(result.duplicate);
        return;
      }
      if (result.run_id !== null) router.push(`/runs/${result.run_id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not submit the run.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="New run"
        description="Upload the OSL, the ETL config, and the output reports. Every OSL requirement is traced into the config and then into the reports."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="border-b">
              <CardTitle>Run details</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 pt-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="customer">
                  Customer name<span className="text-destructive"> *</span>
                </Label>
                <Input
                  id="customer"
                  value={customer}
                  onChange={(event) => setCustomer(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="order">
                  Order number<span className="text-destructive"> *</span>
                </Label>
                <Input
                  id="order"
                  className="mono"
                  value={order}
                  onChange={(event) => setOrder(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="configuration">
                  Configuration ID<span className="text-destructive"> *</span>
                </Label>
                <Input
                  id="configuration"
                  className="mono"
                  value={configurationId}
                  onChange={(event) => setConfigurationId(event.target.value)}
                />
                <span className="text-[0.7rem] text-muted-foreground">
                  Used to version the captured config.
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="run-date">Run date</Label>
                <Input
                  id="run-date"
                  type="date"
                  value={runDate}
                  onChange={(event) => setRunDate(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label htmlFor="notes">Additional notes</Label>
                <Textarea
                  id="notes"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Anything the reviewer should know: special instructions, known deviations, who asked for the run."
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b">
              <CardTitle>Input files</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 pt-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <FileDrop
                  label="OSL — requirement spec"
                  hint="Word document (.docx)"
                  accept=".docx"
                  required
                  file={osl}
                  onChange={setOsl}
                />
                <FileDrop
                  label="ETL config"
                  hint="JSON (.json)"
                  accept=".json"
                  required
                  file={config}
                  onChange={setConfig}
                />
              </div>

              <div>
                <div className="mb-2 text-xs font-medium">
                  Output reports<span className="text-destructive"> *</span>
                  <span className="ml-1 font-normal text-muted-foreground">
                    at least one Excel file
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {OFFERED.map((kind) => (
                    <FileDrop
                      key={kind}
                      label={REPORT_LABELS[kind]}
                      accept=".xlsx"
                      file={reports[kind] ?? null}
                      onChange={(file) => setReports((prev) => ({ ...prev, [kind]: file }))}
                    />
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Submitting hashes every file. If the same inputs were already run, the existing report
              is shown before anything is queued.
            </p>
            <Button disabled={!ready || submitting} onClick={() => void submit("")}>
              <Play className="h-4 w-4" />
              {submitting ? "Submitting…" : "Submit run"}
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>What happens next</CardTitle>
            </CardHeader>
            <CardContent className="text-xs">
              <ol className="list-decimal space-y-1.5 pl-4 leading-relaxed">
                <li>Files are hashed and stored; the run is queued.</li>
                <li>
                  A worker runs the nine stages: parse, extract, describe, trace, compare, reverse
                  pass, report checks, verify, summarize.
                </li>
                <li>The run moves to Needs review.</li>
                <li>You decide each finding, then generate the frozen report.</li>
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4 text-primary" /> Privacy
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">
              Sample rows and personal data never go into a prompt or a log. The model sees
              requirement text, config blocks, and aggregate report values only. Masked columns are
              configured in the admin-ui.
            </CardContent>
          </Card>
        </div>
      </div>

      {duplicate ? (
        <DuplicateDialog
          duplicate={duplicate}
          reason={rerunReason}
          onReason={setRerunReason}
          submitting={submitting}
          onCancel={() => {
            setDuplicate(null);
            setRerunReason("");
          }}
          onConfirm={() => void submit(rerunReason)}
          onOpenExisting={() => router.push(`/runs/${duplicate.run_id}`)}
        />
      ) : null}
    </>
  );
}

interface DuplicateDialogProps {
  duplicate: DuplicateRun;
  reason: string;
  submitting: boolean;
  onReason: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  onOpenExisting: () => void;
}

function DuplicateDialog({
  duplicate,
  reason,
  submitting,
  onReason,
  onCancel,
  onConfirm,
  onOpenExisting,
}: DuplicateDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="duplicate-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <Card className="w-full max-w-2xl">
        <CardHeader className="border-b">
          <CardTitle id="duplicate-title">These inputs were already run</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 pt-4">
          <div className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 p-3 text-xs">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-warn" />
            <p>{duplicate.message}</p>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-md border p-3">
            <div className="text-xs">
              <div className="font-semibold">
                Run VR-{String(duplicate.run_id).padStart(4, "0")}
              </div>
              <div className="text-muted-foreground">
                {fmtTime(duplicate.created_at)} · status {duplicate.status}
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={onOpenExisting}>
              Open existing run
            </Button>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rerun-reason">
              Reason for re-running<span className="text-destructive"> *</span>
            </Label>
            <Textarea
              id="rerun-reason"
              value={reason}
              onChange={(event) => onReason(event.target.value)}
              placeholder="Recorded on the run and in the audit log. For example: the prompt version changed, or a new admin check was added."
            />
          </div>
        </CardContent>
        <div className="flex justify-end gap-2 border-t p-4">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button disabled={!reason.trim() || submitting} onClick={onConfirm}>
            <Play className="h-4 w-4" /> Re-run anyway
          </Button>
        </div>
      </Card>
    </div>
  );
}

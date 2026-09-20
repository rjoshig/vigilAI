"use client";

/**
 * New run: the upload form and the duplicate-inputs dialog.
 *
 * The server decides what counts as a duplicate, because only it knows the input
 * fingerprint and which checks are active. The form's job is to ask for a reason when
 * the server says the inputs were already run (`docs/design.md` "LLM cost controls").
 */

import { AlertTriangle, HelpCircle, Play, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ConfigNotes } from "@/components/config-notes";
import { FieldEffect } from "@/components/explain";
import { FileDrop } from "@/components/file-drop";
import { ReportSlotField, emptyPart, type ReportPart } from "@/components/report-slot";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  Select,
  Textarea,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ArtifactSlot, DuplicateRun, NewRunOptions, TypeDetection } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

const CONFIG_ID_DEBOUNCE_MS = 500;

/** The value as it stood once it has been unchanged for `delayMs`. */
function useDebounced(value: string, delayMs: number): string {
  const [settled, setSettled] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

export default function NewRunPage() {
  const router = useRouter();

  const [customer, setCustomer] = React.useState("");
  const [order, setOrder] = React.useState("");
  const [configurationId, setConfigurationId] = React.useState("");
  // The notes lookup waits until typing pauses, so a person keying an id does not
  // fire one request per character.
  const debouncedConfigurationId = useDebounced(configurationId.trim(), CONFIG_ID_DEBOUNCE_MS);
  const [creditDate, setCreditDate] = React.useState("");
  const [notes, setNotes] = React.useState("");

  const [scope, setScope] = React.useState("");
  const [hasSuppressions, setHasSuppressions] = React.useState(false);

  // Kept as strings because an empty box means "unstated", which is a different
  // answer from zero and must survive the round trip without becoming one.
  const [deliveryNotes, setDeliveryNotes] = React.useState("");

  // The slots are whatever the admin catalog says they are, so switching a report type
  // off in the admin-ui removes it here with no deploy (ADR-020).
  const [options, setOptions] = React.useState<NewRunOptions | null>(null);
  const [files, setFiles] = React.useState<Record<string, File | null>>({});
  // A report slot holds a list of parts, because the same report type can be
  // delivered once per segment or per deliverable (ADR-021 milestone 6.1b).
  const [parts, setParts] = React.useState<Record<string, ReportPart[]>>({});
  const [unsure, setUnsure] = React.useState<TypeDetection | null>(null);
  const [unsureFile, setUnsureFile] = React.useState<File | null>(null);

  const [duplicate, setDuplicate] = React.useState<DuplicateRun | null>(null);
  const [rerunReason, setRerunReason] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api
      .getRunOptions()
      .then((next) => {
        setOptions(next);
        setScope((current) => current || next.scopes[0]?.code || "");
      })
      .catch((caught: unknown) =>
        setError(caught instanceof ApiError ? caught.detail : "Could not load the upload form.")
      );
  }, []);

  const slots = options?.artifacts ?? [];
  const reportSlots = React.useMemo(
    () => (options?.artifacts ?? []).filter((slot) => slot.kind === "report"),
    [options]
  );
  const inputSlots = slots.filter((slot) => slot.kind !== "report");

  function slotParts(key: string): ReportPart[] {
    return parts[key] ?? [];
  }

  function filesIn(key: string): File[] {
    return slotParts(key)
      .map((part) => part.file)
      .filter((file): file is File => file !== null);
  }

  const reportCount = reportSlots.reduce((total, slot) => total + filesIn(slot.key).length, 0);
  const requiredMissing = slots.some((slot) =>
    slot.kind === "report"
      ? slot.is_required && filesIn(slot.key).length === 0
      : slot.is_required && !files[slot.key]
  );
  const ready =
    Boolean(customer.trim() && order.trim() && configurationId.trim()) &&
    !requiredMissing &&
    reportCount > 0;

  /** Give every report slot its first, empty part once the catalog has loaded. */
  React.useEffect(() => {
    if (reportSlots.length === 0) return;
    setParts((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const slot of reportSlots) {
        if (!next[slot.key] || next[slot.key].length === 0) {
          next[slot.key] = [emptyPart()];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [reportSlots]);

  function patchPart(key: string, partId: string, patch: Partial<ReportPart>) {
    setParts((prev) => ({
      ...prev,
      [key]: (prev[key] ?? []).map((part) => (part.id === partId ? { ...part, ...patch } : part)),
    }));
  }

  /**
   * Ask the backend what a workbook is and show the answer.
   *
   * A failure is swallowed on purpose: detection is a convenience and must never stand
   * between someone and a submission, so the slot they chose simply stands.
   */
  async function detect(key: string, partId: string, file: File) {
    patchPart(key, partId, { detecting: true, detection: null });
    try {
      const detection = await api.detectType(file);
      patchPart(key, partId, { detecting: false, detection });
    } catch {
      patchPart(key, partId, { detecting: false, detection: null });
    }
  }

  function setPartFile(key: string, partId: string, file: File | null) {
    patchPart(key, partId, { file, detection: null });
    if (file) void detect(key, partId, file);
  }

  function addPart(key: string) {
    setParts((prev) => ({ ...prev, [key]: [...(prev[key] ?? []), emptyPart()] }));
  }

  function removePart(key: string, partId: string) {
    setParts((prev) => {
      const remaining = (prev[key] ?? []).filter((part) => part.id !== partId);
      return { ...prev, [key]: remaining.length > 0 ? remaining : [emptyPart()] };
    });
  }

  /** Put an already-chosen file into another slot, only ever on a person's press. */
  function movePart(fromKey: string, partId: string, toKey: string) {
    if (fromKey === toKey) return;
    const moving = slotParts(fromKey).find((part) => part.id === partId);
    if (!moving) return;
    setParts((prev) => {
      const source = (prev[fromKey] ?? []).filter((part) => part.id !== partId);
      const target = (prev[toKey] ?? []).filter((part) => part.file !== null);
      return {
        ...prev,
        [fromKey]: source.length > 0 ? source : [emptyPart()],
        [toKey]: [...target, { ...moving, detection: null }],
      };
    });
  }

  /** Place a file the person could not classify into whichever slot detection named. */
  function placeDetected(file: File, key: string) {
    setParts((prev) => {
      const target = (prev[key] ?? []).filter((part) => part.file !== null);
      return { ...prev, [key]: [...target, { ...emptyPart(), file }] };
    });
    setUnsure(null);
    setUnsureFile(null);
  }

  async function detectUnsure(file: File) {
    setUnsureFile(file);
    setUnsure(null);
    try {
      const detection = await api.detectType(file);
      if (detection.verdict === "confident" && detection.key) {
        placeDetected(file, detection.key);
        return;
      }
      setUnsure(detection);
    } catch {
      // Same rule as the per-slot call: no opinion rather than an obstacle.
      setUnsureFile(null);
    }
  }

  function buildForm(reason: string): FormData {
    const form = new FormData();
    form.set("customer_name", customer.trim());
    form.set("order_number", order.trim());
    form.set("configuration_id", configurationId.trim());
    form.set("notes", notes);
    form.set("scope", scope);
    form.set("has_suppressions", hasSuppressions ? "true" : "false");
    if (creditDate) form.set("credit_date", creditDate);
    if (reason) form.set("rerun_reason", reason);
    if (deliveryNotes.trim()) form.set("delivery_notes", deliveryNotes.trim());
    for (const slot of slots) {
      if (slot.kind === "report") continue;
      const file = files[slot.key];
      if (file) form.set(slot.key, file);
    }
    // Repeated parts under one key, with the labels in the same order: the server
    // pairs the nth label with the nth file, so a gap would mislabel everything after
    // it. Labels are sent only when at least one was written, which keeps the ordinary
    // one-file-per-slot request exactly as it was.
    for (const slot of reportSlots) {
      const present = slotParts(slot.key).filter((part) => part.file !== null);
      for (const part of present) {
        if (part.file) form.append(slot.key, part.file);
      }
      if (present.some((part) => part.label.trim())) {
        for (const part of present) form.append(`${slot.key}__label`, part.label.trim());
      }
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
                <FieldEffect
                  kind="record"
                  note="Scopes rules and aliases to this customer, and is compared with the customer your configuration file names."
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
                <span className="text-[0.7rem] text-muted-foreground">
                  Identifies the order in the run list and the report. Not sent to the model.
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="configuration">Configuration ID *</Label>
                <Input
                  id="configuration"
                  className="mono"
                  value={configurationId}
                  onChange={(event) => setConfigurationId(event.target.value)}
                />
                <span className="text-[0.7rem] text-muted-foreground">
                  The order&apos;s ETL configuration number, the Solution Canvas config number.
                  Required, and it may repeat: the same configuration is run again months later, and
                  the credit date tells the runs apart. Every run still gets its own id.
                </span>
                <FieldEffect
                  kind="record"
                  note="Groups this run with earlier runs of the same configuration so drift can be compared, and is checked against the id inside your configuration file before anything is validated."
                />
              </div>
              {debouncedConfigurationId ? (
                <div className="sm:col-span-2">
                  <ConfigNotes configurationId={debouncedConfigurationId} mode="add" />
                </div>
              ) : null}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="credit-date">Credit date</Label>
                <Input
                  id="credit-date"
                  type="date"
                  value={creditDate}
                  onChange={(event) => setCreditDate(event.target.value)}
                />
                <span className="text-[0.7rem] text-muted-foreground">
                  The date the delivery is cut as of.
                </span>
                <FieldEffect
                  kind="code"
                  note="Compared with the date your reports say they are cut as of. A disagreement stops the run before it starts, so a delivery cut for the wrong month is caught here rather than after it is validated."
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="scope">Delivery programme</Label>
                <Select id="scope" value={scope} onChange={(event) => setScope(event.target.value)}>
                  {(options?.scopes ?? []).map((option) => (
                    <option key={option.code} value={option.code}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <span className="text-[0.7rem] text-muted-foreground">
                  {options?.scopes.find((option) => option.code === scope)?.description ??
                    "Which kind of delivery this is."}{" "}
                  Sent to the model as background, with the programme&apos;s rules. Choosing the
                  right programme improves the validation.
                </span>
              </div>
              <fieldset className="flex flex-col gap-1.5">
                <legend className="text-xs font-medium">Suppressions applied</legend>
                <div className="flex items-center gap-4 pt-1">
                  <label className="flex items-center gap-1.5 text-sm">
                    <input
                      type="radio"
                      name="has-suppressions"
                      checked={!hasSuppressions}
                      onChange={() => setHasSuppressions(false)}
                    />
                    No
                  </label>
                  <label className="flex items-center gap-1.5 text-sm">
                    <input
                      type="radio"
                      name="has-suppressions"
                      checked={hasSuppressions}
                      onChange={() => setHasSuppressions(true)}
                    />
                    Yes
                  </label>
                </div>
                <span className="text-[0.7rem] text-muted-foreground">
                  Whether records were suppressed before delivery. Sent to the model as background.
                </span>
              </fieldset>
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label htmlFor="delivery-notes">Delivery notes</Label>
                <Input
                  id="delivery-notes"
                  value={deliveryNotes}
                  onChange={(event) => setDeliveryNotes(event.target.value)}
                  placeholder="Anything about the delivery itself: which segments were sent, what is still to come."
                />
                <FieldEffect
                  kind="model"
                  note="The more accurately this describes the delivery, the better the findings: it tells the model what it is looking at before it judges anything."
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
                <FieldEffect
                  kind="reviewer"
                  note="Shown on the run and to whoever reviews it. It reaches no model and changes no finding."
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
                {inputSlots.map((slot) => (
                  <FileDrop
                    key={slot.key}
                    label={slot.label}
                    hint={slot.description || `Expects ${slot.accept}`}
                    accept={slot.accept}
                    required={slot.is_required}
                    file={files[slot.key] ?? null}
                    onChange={(file) => setFiles((prev) => ({ ...prev, [slot.key]: file }))}
                  />
                ))}
              </div>

              <div>
                <div className="mb-2 text-xs font-medium">
                  Output reports<span className="text-destructive"> *</span>
                  <span className="ml-1 font-normal text-muted-foreground">
                    at least one Excel file
                  </span>
                </div>
                <p className="mb-2 text-[0.7rem] text-muted-foreground">
                  A slot can hold several files. Label each one when it does: a finding names the
                  file it came from, and &quot;the field distribution is wrong&quot; is useless when
                  five were uploaded.
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {reportSlots.map((slot) => (
                    <ReportSlotField
                      key={slot.key}
                      slot={slot}
                      parts={slotParts(slot.key)}
                      targets={reportSlots}
                      onFile={(partId, file) => setPartFile(slot.key, partId, file)}
                      onLabel={(partId, label) => patchPart(slot.key, partId, { label })}
                      onAdd={() => addPart(slot.key)}
                      onRemove={(partId) => removePart(slot.key, partId)}
                      onMove={(partId, targetKey) => movePart(slot.key, partId, targetKey)}
                      onDismissDetection={(partId) =>
                        patchPart(slot.key, partId, { detection: null })
                      }
                    />
                  ))}
                </div>

                <UnsureControl
                  detection={unsure}
                  fileName={unsureFile?.name ?? ""}
                  slots={reportSlots}
                  onFile={(file) => void detectUnsure(file)}
                  onChoose={(key) => {
                    if (unsureFile) placeDetected(unsureFile, key);
                  }}
                  onCancel={() => {
                    setUnsure(null);
                    setUnsureFile(null);
                  }}
                />
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

interface UnsureControlProps {
  detection: TypeDetection | null;
  fileName: string;
  slots: ArtifactSlot[];
  onFile: (file: File) => void;
  onChoose: (key: string) => void;
  onCancel: () => void;
}

/**
 * The way in for someone who does not know what their workbook is called.
 *
 * Nobody should have to know that their file is a "field distribution". A confident
 * detection drops the file straight into the right slot; anything less asks, because
 * a wrong silent assignment is worse than a question.
 */
function UnsureControl({
  detection,
  fileName,
  slots,
  onFile,
  onChoose,
  onCancel,
}: UnsureControlProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div className="mt-3 rounded-md border border-dashed p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
          <HelpCircle className="h-4 w-4" /> I&apos;m not sure what this is
        </Button>
        <span className="text-muted-foreground">
          Choose the file and it will be identified and put in the right slot.
        </span>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(event) => {
            const chosen = event.target.files?.[0];
            if (chosen) onFile(chosen);
            event.target.value = "";
          }}
        />
      </div>

      {detection ? (
        <div className="mt-2 rounded-md border bg-muted/40 p-2 text-[0.7rem] leading-relaxed">
          <p>
            <b>
              {fileName}:{" "}
              {detection.verdict === "ambiguous"
                ? "this could be more than one thing."
                : "this did not match any known report type."}
            </b>{" "}
            {detection.reason}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(detection.candidates.length > 0
              ? detection.candidates.filter((candidate) =>
                  slots.some((slot) => slot.key === candidate.key)
                )
              : slots.map((slot) => ({ key: slot.key, label: slot.label, score: 0 }))
            ).map((candidate) => (
              <Button
                key={candidate.key}
                size="xs"
                variant="outline"
                onClick={() => onChoose(candidate.key)}
              >
                It is the {candidate.label}
              </Button>
            ))}
            <Button size="xs" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

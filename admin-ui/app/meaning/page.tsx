"use client";

/**
 * Meaning: what each OSL requirement answers to, per delivery programme (Phase 6.10).
 *
 * Press Map and the model reads the samples in scope and proposes, for every
 * requirement, the configuration block that implements it and the report cells that
 * evidence it, asking a question when it cannot place one. Confirm a row and code
 * compiles it into a shadow check (and a shadow compliance rule when suggested).
 * The model proposes; a person confirms; code compares (ADR-033).
 */

import { Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Explain, FieldEffect } from "@/components/explain";
import { BulkBar } from "@/components/bulk-bar";
import { GuideEditor } from "@/components/guide-editor";
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
  Label,
  PageHeader,
  Select,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { VersionsPanel } from "@/components/versions-panel";
import { api, ApiError } from "@/lib/api";
import type {
  ArtifactType,
  MeaningEntry,
  MeaningEntryPatch,
  MeaningSamples,
  MeaningStatus,
  Scope,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<MeaningStatus, "success" | "warn" | "info" | "muted"> = {
  confirmed: "success",
  open: "warn",
  proposed: "info",
  rejected: "muted",
};

type Tab = "requirements" | "cells";

/**
 * What each missing artifact is called in a sentence somebody can act on.
 *
 * The API answers with the artifact keys the interview needs. "osl, config" is a
 * correct answer to a question nobody asked; what an administrator needs to know is
 * which file to go and upload.
 */
const MISSING_LABELS: Record<string, string> = {
  osl: "example OSL document",
  config: "example ETL configuration",
};

export default function MeaningPage() {
  const [scope, setScope] = React.useState("");
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);
  const [entries, setEntries] = React.useState<MeaningEntry[] | null>(null);
  const [samples, setSamples] = React.useState<MeaningSamples | null>(null);
  const [types, setTypes] = React.useState<ArtifactType[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [mapping, setMapping] = React.useState(false);
  const [lastRun, setLastRun] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<number[]>([]);
  const [tab, setTab] = React.useState<Tab>("requirements");
  const [showVersions, setShowVersions] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [nextEntries, nextSamples, nextProgrammes, nextTypes] = await Promise.all([
        api.listMeaning(scope),
        api.meaningSamples(scope),
        api.listScopes(),
        api.listArtifactTypes(),
      ]);
      setEntries(nextEntries);
      setSamples(nextSamples);
      setProgrammes(nextProgrammes);
      setTypes(nextTypes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [scope]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
    } finally {
      setBusy(false);
    }
  }

  async function map() {
    setMapping(true);
    setError(null);
    try {
      const result = await api.proposeMeaning(scope);
      setLastRun(
        `${result.sections} section(s) read · ${result.proposed} proposed · ${result.open} open with a question · ${result.updated} updated · ${result.skipped_confirmed} confirmed left alone · ${result.calls} model call(s), ${result.cached} from cache`
      );
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "The model could not map this scope.");
    } finally {
      setMapping(false);
    }
  }

  const scopeLabel = scope
    ? (programmes?.find((p) => p.code === scope)?.label ?? scope)
    : "Global (every programme)";
  const reportTypes = (types ?? []).filter((t) => t.kind === "report");

  return (
    <>
      <PageHeader
        explain={
          <Explain label="What mapping is for">
            Where each OSL requirement answers to: which configuration path implements it, and which
            report cells evidence it. The model proposes from the samples, you confirm, and code
            compiles a confirmed row into a shadow check.
            <br />
            <br />
            <b>Why do this at all?</b> Without a mapping the model works out where every requirement
            lands <i>from scratch, on every run</i> — reading the OSL, then the configuration, then
            the reports, and deciding which part answers which. That is the step it is least certain
            about and the one it can answer differently on two runs of the same delivery. A
            confirmed mapping replaces the guessing with a fact.
            <br />
            <br />
            <b>What one confirmed row actually does — two things at once:</b>
            <br />
            <b>1. The AI reads it.</b> It goes into the prompt at tracing and at verification as
            background:{" "}
            <i>this cell means X, it answers to OSL section Y and configuration path Z</i>. The
            model stops deriving that and spends its attention on whether the delivery is right,
            which is the judgment you actually want from it.
            <br />
            <b>2. Code turns it into a check.</b> A row with both a configuration path and a locator
            that lands on your samples compiles into two named values and a comparison code runs
            itself — no model, no tokens, the same answer every time. It starts in shadow, so you
            watch it fire before it counts.
            <br />
            <br />
            <b>What gets better:</b> fewer requirements come back as <i>could not trace</i>; the
            same requirement resolves the same way every month instead of being re-derived; and each
            confirmed row quietly adds a deterministic check you did not have to write.
            <br />
            <br />
            <b>Why you confirm rather than the model.</b> Nothing the model proposes acts on
            anything until a person accepts it (ADR-021). A wrong mapping is worse than none — it
            teaches the tool the wrong place to look — so the model does the reading and you do the
            deciding.
            <br />
            <br />
            Scoped globally or per programme. A programme entry with the same key as a global one
            replaces it on that programme&rsquo;s runs.
          </Explain>
        }
        title="Meaning"
        description="What each OSL requirement answers to in the configuration and the reports, globally and per delivery programme. The model proposes from the samples, you confirm, and code turns a confirmed row into a check that runs in shadow until you activate it on the Rules screen. Sent to the model as background on every run; code does the comparing."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <Card className="mb-4">
        <CardContent className="grid gap-3 pt-4 lg:grid-cols-[1fr_2fr_auto]">
          <div className="flex flex-col gap-1">
            <Label htmlFor="meaning-scope">Scope</Label>
            <Select
              id="meaning-scope"
              value={scope}
              onChange={(event) => {
                setScope(event.target.value);
                setSelected([]);
              }}
            >
              <option value="">Global (every programme)</option>
              {(programmes ?? []).map((programme) => (
                <option key={programme.code} value={programme.code}>
                  {programme.label} ({programme.code})
                </option>
              ))}
            </Select>
            <span className="text-[0.7rem] text-muted-foreground">
              A programme reads its own samples where it has any, else the global ones. At run time
              a programme entry with the same key as a global one replaces it.
            </span>
          </div>
          <div className="text-xs">
            <div className="mb-1 font-semibold">Samples in scope</div>
            {!samples ? (
              <Skeleton className="h-10" />
            ) : samples.samples.length === 0 ? (
              <span className="text-muted-foreground">
                None yet. Upload an OSL, a configuration and the reports on Artifact types.
              </span>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {samples.samples.map((sample) => (
                  <span
                    key={sample.sample_id}
                    className="inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-0.5 text-[0.7rem]"
                  >
                    <span className="mono">{sample.artifact_key}</span>
                    {sample.label ? ` · ${sample.label}` : ""}
                    <Badge tone={sample.scope_code ? "outline" : "muted"}>
                      {sample.scope_code || "global"}
                    </Badge>
                  </span>
                ))}
              </div>
            )}
            {samples && samples.missing.length > 0 ? (
              <div className="mt-1 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-destructive">
                <b>Map cannot run yet.</b> It reads one example of each artifact to work out where
                requirements land, and {scopeLabel} has no{" "}
                {samples.missing.map((key) => MISSING_LABELS[key] ?? key).join(" and no ")} to read.
                <br />
                <Link href="/artifacts" className="underline underline-offset-2">
                  Upload one on Artifact types
                </Link>{" "}
                — a made-up file of the right shape is enough, and it is never used when a delivery
                is checked. A programme with none of its own falls back to the global samples.
              </div>
            ) : null}
            <FieldEffect
              kind="reference"
              className="mt-1.5"
              note="The AI reads these example files when you press Map, to suggest where each requirement fits. They are not used when a delivery is checked — the mappings you confirm below are."
            />
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button
              disabled={mapping || busy || !samples || samples.missing.length > 0}
              onClick={() => void map()}
            >
              <Sparkles className="h-3.5 w-3.5" /> {mapping ? "Mapping…" : `Map ${scopeLabel}`}
            </Button>
            <Button variant="ghost" size="xs" onClick={() => setShowVersions(!showVersions)}>
              {showVersions ? "Hide versions" : "Versions"}
            </Button>
          </div>
        </CardContent>
        {lastRun ? (
          <CardContent className="border-t pt-3 text-xs text-muted-foreground">
            {lastRun}
          </CardContent>
        ) : null}
        {showVersions ? (
          <CardContent className="border-t pt-3">
            <VersionsPanel
              kind="meaning"
              objectKey={scope || "global"}
              onReverted={() => void load()}
            />
          </CardContent>
        ) : null}
      </Card>

      <div className="mb-4 flex gap-1 border-b" role="tablist">
        {(
          [
            ["requirements", "By requirement"],
            ["cells", "By report cell"],
          ] as [Tab, string][]
        ).map(([name, label]) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            className={cn(
              "-mb-px border-b-2 px-3.5 py-2 text-sm font-medium",
              tab === name
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
            {name === "requirements" && entries ? (
              <span className="ml-1.5 text-xs text-muted-foreground">{entries.length}</span>
            ) : null}
          </button>
        ))}
      </div>

      {tab === "cells" ? (
        <div className="grid gap-4">
          <p className="text-xs text-muted-foreground">
            Cell-level meaning lives on each report type: what a cell means, where it answers to,
            with examples from the samples. The same editor is on Artifact types.
          </p>
          {reportTypes.map((type) => (
            <Card key={type.key}>
              <CardHeader className="border-b">
                <CardTitle>{type.label}</CardTitle>
              </CardHeader>
              <CardContent className="pt-1">
                <GuideEditor type={type} busy={busy} onSaved={() => void load()} />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : !entries ? (
        <Skeleton className="h-64" />
      ) : entries.length === 0 ? (
        <EmptyState
          title="No requirement mappings in this scope"
          hint="Press Map to have the model propose them from the samples, or add one by hand below."
        />
      ) : (
        <>
          <BulkBar
            count={selected.length}
            busy={busy}
            actions={[
              { word: "confirm", label: "Confirm selected" },
              { word: "reject", label: "Reject selected" },
              { word: "delete", label: "Delete selected", destructive: true },
            ]}
            onClear={() => setSelected([])}
            onAct={(word) =>
              act(word, async () => {
                await api.bulkMeaning(selected, word as "confirm" | "reject" | "delete", word);
                setSelected([]);
              })
            }
          />
          <div className="grid gap-3">
            {entries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                reportTypes={reportTypes}
                busy={busy}
                selected={selected.includes(entry.id)}
                onSelect={() =>
                  setSelected((current) =>
                    current.includes(entry.id)
                      ? current.filter((one) => one !== entry.id)
                      : [...current, entry.id]
                  )
                }
                onPatch={(patch) => act("save the entry", () => api.updateMeaning(entry.id, patch))}
              />
            ))}
          </div>
        </>
      )}

      {tab === "requirements" ? (
        <NewEntry
          scope={scope}
          reportTypes={reportTypes}
          busy={busy}
          onCreate={(payload) => act("add the entry", () => api.createMeaning(payload))}
        />
      ) : null}
    </>
  );
}

function EntryCard({
  entry,
  reportTypes,
  busy,
  selected,
  onSelect,
  onPatch,
}: {
  entry: MeaningEntry;
  reportTypes: ArtifactType[];
  busy: boolean;
  selected: boolean;
  onSelect: () => void;
  onPatch: (patch: MeaningEntryPatch) => void;
}) {
  const [draft, setDraft] = React.useState<MeaningEntryPatch>({});
  const [promoted, setPromoted] = React.useState(false);
  const [promoteError, setPromoteError] = React.useState<string | null>(null);
  React.useEffect(() => setDraft({}), [entry.updated_at]);

  /** Teach this confirmed mapping to the model as a worked example (ADR-038). */
  async function promote() {
    try {
      await api.promoteExample({ source: "meaning", id: entry.id });
      setPromoted(true);
      setPromoteError(null);
    } catch (caught) {
      setPromoteError(
        caught instanceof ApiError ? caught.detail : "Could not add it to the examples."
      );
    }
  }
  const cell = draft.report_cells?.[0] ?? entry.report_cells[0];
  const dirty = Object.keys(draft).length > 0;

  function setCell(changes: Partial<MeaningEntry["report_cells"][number]>) {
    const base = cell ?? {
      report_key: reportTypes[0]?.key ?? "",
      sheet: "",
      kind: "label" as const,
      cell: "",
      label: "",
      label_column: 0,
      value_column: 1,
    };
    setDraft({ ...draft, report_cells: [{ ...base, ...changes }, ...entry.report_cells.slice(1)] });
  }

  const sheets = reportTypes.find((t) => t.key === (cell?.report_key ?? ""))?.sheets ?? [];

  return (
    <Card
      className={cn(
        "border-l-4",
        entry.status === "confirmed"
          ? "border-l-success"
          : entry.status === "open"
            ? "border-l-warn"
            : entry.status === "rejected"
              ? "border-l-muted opacity-70"
              : "border-l-info"
      )}
      data-testid={`meaning-${entry.key}`}
    >
      <CardHeader className="flex-row items-start justify-between gap-2 border-b">
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            aria-label={`Select ${entry.key}`}
            className="mt-1"
            checked={selected}
            onChange={onSelect}
          />
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2">
              <span className="mono text-xs text-muted-foreground">
                OSL {entry.osl_section} {entry.osl_phrase}
              </span>
              <Badge tone={STATUS_TONE[entry.status]}>{entry.status}</Badge>
              {entry.compiled_check ? <Badge tone="outline">shadow check</Badge> : null}
              {entry.compiled_compliance ? (
                <Badge tone="outline">shadow compliance rule</Badge>
              ) : null}
              <span className="text-xs text-muted-foreground">
                {entry.proposed_by === "model"
                  ? `model · ${Math.round(entry.confidence * 100)}%`
                  : "by hand"}
              </span>
            </CardTitle>
            <p className="mt-1 text-sm">{entry.requirement_text || entry.key}</p>
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          {entry.status !== "confirmed" ? (
            <Button
              size="xs"
              disabled={busy}
              onClick={() => onPatch({ ...draft, status: "confirmed" })}
            >
              Confirm
            </Button>
          ) : null}
          {entry.status === "confirmed" ? (
            // A mapping a person confirmed is the model being told what this
            // requirement answers to, which is what a worked example teaches (ADR-038).
            <Button
              size="xs"
              variant="outline"
              disabled={busy || promoted}
              title="Add this mapping to the model's worked examples for tracing"
              onClick={() => void promote()}
            >
              {promoted ? "Taught" : "Use as example"}
            </Button>
          ) : null}
          {entry.status !== "rejected" ? (
            <Button
              size="xs"
              variant="outline"
              disabled={busy}
              onClick={() => onPatch({ status: "rejected" })}
            >
              Reject
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="grid gap-2 pt-3 text-xs">
        {promoteError ? <p className="text-destructive">{promoteError}</p> : null}
        {entry.question ? (
          <div className="rounded-md border border-warn/50 bg-warn/10 p-2">
            <b>The model asks:</b> {entry.question}
          </div>
        ) : null}
        <FieldEffect
          kind="model"
          className="mb-2"
          note="Two things at once. The AI reads it at tracing and verification as background — it stops working out where this requirement answers to and reads the answer instead, which is the step it is least certain about. And where the row has a configuration path and a locator that lands on your samples, code compiles it into a comparison it runs itself, in shadow, at no token cost."
        />
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_6rem]">
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-cfg-${entry.id}`}>Configuration path</Label>
            <Input
              id={`m-cfg-${entry.id}`}
              className="mono"
              value={draft.config_path ?? entry.config_path}
              onChange={(event) => setDraft({ ...draft, config_path: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-rep-${entry.id}`}>Report</Label>
            <Select
              id={`m-rep-${entry.id}`}
              value={cell?.report_key ?? ""}
              onChange={(event) => setCell({ report_key: event.target.value })}
            >
              <option value="">(none)</option>
              {reportTypes.map((type) => (
                <option key={type.key} value={type.key}>
                  {type.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-lbl-${entry.id}`}>Sheet · label</Label>
            <div className="flex gap-1">
              <Select
                aria-label="Sheet"
                className="w-1/2"
                value={cell?.sheet ?? ""}
                onChange={(event) => setCell({ sheet: event.target.value })}
              >
                <option value="">(first)</option>
                {sheets.map((sheet) => (
                  <option key={sheet} value={sheet}>
                    {sheet}
                  </option>
                ))}
              </Select>
              <Input
                id={`m-lbl-${entry.id}`}
                className="w-1/2"
                placeholder="label"
                value={cell?.label ?? ""}
                onChange={(event) => setCell({ label: event.target.value, kind: "label" })}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-col-${entry.id}`}>Value col</Label>
            <Input
              id={`m-col-${entry.id}`}
              type="number"
              min={0}
              value={cell?.value_column ?? 1}
              onChange={(event) => setCell({ value_column: Number(event.target.value) })}
            />
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-val-${entry.id}`}>What to validate</Label>
            <Textarea
              id={`m-val-${entry.id}`}
              rows={2}
              value={draft.validate ?? entry.validate}
              onChange={(event) => setDraft({ ...draft, validate: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-cmp-${entry.id}`}>Code checks</Label>
            <Select
              id={`m-cmp-${entry.id}`}
              value={draft.comparison ?? entry.comparison}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  comparison: event.target.value as "" | "equals" | "reconciles",
                })
              }
            >
              <option value="">Nothing (explanation only)</option>
              <option value="equals">Report equals the configuration value</option>
              <option value="reconciles">Reconciles within a tolerance</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`m-note-${entry.id}`}>Your note</Label>
            <Textarea
              id={`m-note-${entry.id}`}
              rows={2}
              placeholder="What a person should know about this mapping"
              value={draft.note ?? entry.note}
              onChange={(event) => setDraft({ ...draft, note: event.target.value })}
            />
          </div>
        </div>
        {entry.compliance_suggestion ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 p-2">
            <b>Suggested compliance rule:</b>
            <span className="mono">{entry.compliance_suggestion.json_path_contains}</span>
            <span className="text-muted-foreground">
              {entry.compliance_suggestion.reasoning}. Confirming this row creates it in shadow.
            </span>
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              onClick={() => onPatch({ drop_compliance_suggestion: true })}
            >
              Drop suggestion
            </Button>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-muted-foreground">
            {entry.examples.length > 0
              ? `In the samples: ${entry.examples.map((e) => `${e.label || e.sample_id} = ${e.value}`).join(", ")}`
              : entry.status === "confirmed" &&
                  (draft.report_cells ?? entry.report_cells).length > 0
                ? "The report cell resolved on no sample; nothing compiles until it does."
                : ""}
          </span>
          {dirty ? (
            <Button size="xs" variant="outline" disabled={busy} onClick={() => onPatch(draft)}>
              Save changes
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function NewEntry({
  scope,
  reportTypes,
  busy,
  onCreate,
}: {
  scope: string;
  reportTypes: ArtifactType[];
  busy: boolean;
  onCreate: (payload: Record<string, unknown>) => void;
}) {
  const [key, setKey] = React.useState("");
  const [section, setSection] = React.useState("");
  const [text, setText] = React.useState("");
  const [configPath, setConfigPath] = React.useState("");
  const [reportKey, setReportKey] = React.useState("");
  const [label, setLabel] = React.useState("");

  return (
    <Card className="mt-4">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-1">
          Add a mapping by hand
          <Explain label="When to add one by hand">
            Press <b>Map</b> first — the model proposes from your samples and you confirm, which is
            faster and less error-prone than typing paths.
            <br />
            <br />
            <b>Add one by hand when the model cannot see it:</b> a requirement the samples
            don&rsquo;t cover, a cell that only appears in some months, or a mapping you already
            know and would rather not wait to be proposed.
            <br />
            <br />
            <b>It does the same work either way.</b> A hand-written row reaches the model as
            background at tracing and verification, and compiles into a code check exactly as a
            confirmed one does. The only difference is who wrote it — which is why it starts
            confirmed rather than waiting for you to confirm your own entry.
            <br />
            <br />
            <b>Get the configuration path right.</b> The path is what makes a row compile into a
            check; a row without one still helps the AI read the delivery, but code has nothing to
            compare and no check is born.
          </Explain>
        </CardTitle>
        <span className="text-[0.7rem] text-muted-foreground">
          Starts confirmed. Give it the same key as a global entry to override that entry for this
          programme.
        </span>
      </CardHeader>
      <CardContent className="grid gap-3 pt-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="mn-key">Key</Label>
          <Input
            id="mn-key"
            className="mono"
            placeholder="geography"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mn-sec">OSL section</Label>
          <Input
            id="mn-sec"
            placeholder="3"
            value={section}
            onChange={(e) => setSection(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mn-cfg">Configuration path</Label>
          <Input
            id="mn-cfg"
            className="mono"
            placeholder="filters[0]"
            value={configPath}
            onChange={(e) => setConfigPath(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1 sm:col-span-3">
          <Label htmlFor="mn-text">Requirement, in the OSL&apos;s words</Label>
          <Input id="mn-text" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mn-rep">Report</Label>
          <Select id="mn-rep" value={reportKey} onChange={(e) => setReportKey(e.target.value)}>
            <option value="">(none)</option>
            {reportTypes.map((type) => (
              <option key={type.key} value={type.key}>
                {type.label}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mn-lbl">Row label</Label>
          <Input id="mn-lbl" value={label} onChange={(e) => setLabel(e.target.value)} />
        </div>
        <div className="flex items-end">
          <Button
            disabled={busy || !key.trim()}
            onClick={() => {
              onCreate({
                scope_code: scope,
                key: key.trim(),
                osl_section: section.trim(),
                requirement_text: text.trim(),
                config_path: configPath.trim(),
                report_cells: reportKey
                  ? [
                      {
                        report_key: reportKey,
                        sheet: "",
                        kind: "label",
                        cell: "",
                        label: label.trim(),
                        label_column: 0,
                        value_column: 1,
                      },
                    ]
                  : [],
              });
              setKey("");
              setText("");
              setConfigPath("");
              setLabel("");
            }}
          >
            Add mapping
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

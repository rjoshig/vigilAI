"use client";

/**
 * Artifact types: what the tool accepts, what each one means, and what the model
 * should look at in it (ADR-020).
 *
 * Everything here is optional. A type with no description and no guidance behaves
 * exactly as it did before this screen existed, which is why the guidance field says
 * so rather than looking like a required setting.
 */

import { Download, Eye, Plus, Upload } from "lucide-react";
import * as React from "react";

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
  TD,
  TH,
  TR,
  Table,
  Textarea,
} from "@/components/ui/primitives";
import { BulkBar } from "@/components/bulk-bar";
import { DeleteButton } from "@/components/confirm-delete";
import { GuideEditor } from "@/components/guide-editor";
import { VersionsPanel } from "@/components/versions-panel";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { versionLabel } from "@/lib/versions";
import type { ArtifactType, NamedValue, Sample, SamplePreview, Scope } from "@/lib/types";

const EMPTY_POINTER = {
  name: "",
  report_type: "billing" as string,
  sheet: "",
  kind: "label" as "label" | "cell",
  cell: "",
  label: "",
  label_column: 0,
  value_column: 1,
  description: "",
};

const NEW_TYPE = {
  key: "",
  label: "",
  kind: "report" as const,
  description: "",
  ai_context: "",
  is_active: true,
  is_required: false,
  sort_order: 100,
};

type InputGroup = ArtifactType["kind"];

/** The three kinds of input, each its own tab, so an OSL is never mistaken for a report. */
const INPUT_GROUPS: { key: InputGroup; label: string; title: string; hint: string }[] = [
  {
    key: "osl",
    label: "Requirements (OSL)",
    title: "The OSL — the requirement specification",
    hint: "A Word or PDF document. The source of truth every other input is validated against.",
  },
  {
    key: "config",
    label: "Solution Canvas (ETL configuration)",
    title: "The ETL configuration — the Solution Canvas config JSON",
    hint: "What the delivery was actually built to do. Validated against the OSL.",
  },
  {
    key: "report",
    label: "Reports",
    title: "Output reports",
    hint: "Excel workbooks the delivery produced. Switching a type off removes its upload slot for every user, at once. Named values and validation guides belong here.",
  },
];

export default function ArtifactsPage() {
  const [types, setTypes] = React.useState<ArtifactType[] | null>(null);
  const [values, setValues] = React.useState<NamedValue[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [versions, setVersions] = React.useState<string | null>(null);
  const [guide, setGuide] = React.useState<string | null>(null);
  const [selectedValues, setSelectedValues] = React.useState<number[]>([]);
  const [adding, setAdding] = React.useState(false);
  const [newType, setNewType] = React.useState({ ...NEW_TYPE });
  const [draft, setDraft] = React.useState({ ...EMPTY_POINTER });
  const [busy, setBusy] = React.useState(false);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [nextTypes, nextValues, nextProgrammes] = await Promise.all([
        api.listArtifactTypes(),
        api.listNamedValues(),
        api.listScopes(),
      ]);
      setTypes(nextTypes);
      setValues(nextValues);
      setProgrammes(nextProgrammes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

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

  function save(type: ArtifactType, changes: Partial<ArtifactType>) {
    const merged = { ...type, ...changes };
    return act("save the artifact type", () =>
      api.saveArtifactType({
        key: merged.key,
        label: merged.label,
        kind: merged.kind,
        description: merged.description,
        ai_context: merged.ai_context,
        is_active: merged.is_active,
        is_required: merged.is_required,
        sort_order: merged.sort_order,
      })
    );
  }

  const [group, setGroup] = React.useState<InputGroup>("osl");
  const shownTypes = (types ?? []).filter((t) => t.kind === group);
  const reportKeys = (types ?? []).filter((t) => t.kind === "report").map((t) => t.key);
  const sheets = types?.find((t) => t.key === draft.report_type)?.sheets ?? [];

  return (
    <>
      <PageHeader
        title="Artifact types & meaning"
        description="Which inputs the tool accepts, what each one means, and what the model should pay attention to. Leave the guidance empty and the model reads the document exactly as it does today."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="mb-4 flex gap-1 border-b" role="tablist" aria-label="Input types">
        {INPUT_GROUPS.map((one) => (
          <button
            key={one.key}
            type="button"
            role="tab"
            aria-selected={group === one.key}
            onClick={() => setGroup(one.key)}
            className={cn(
              "-mb-px border-b-2 px-3.5 py-2 text-sm font-medium",
              group === one.key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {one.label}
            {types ? (
              <span className="ml-1.5 text-xs text-muted-foreground">
                {types.filter((t) => t.kind === one.key).length}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <Card className="mb-4 p-0">
        <CardHeader className="flex-row items-center justify-between border-b">
          <div>
            <CardTitle>{INPUT_GROUPS.find((one) => one.key === group)?.title}</CardTitle>
            <span className="text-[0.7rem] text-muted-foreground">
              {INPUT_GROUPS.find((one) => one.key === group)?.hint}
            </span>
          </div>
          {group === "report" ? (
            <Button size="xs" variant="outline" onClick={() => setAdding(!adding)}>
              <Plus className="h-3.5 w-3.5" /> Add a report type
            </Button>
          ) : null}
        </CardHeader>

        {adding ? (
          <CardContent className="grid gap-3 border-b bg-muted/30 pt-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="at-key">Key</Label>
              <Input
                id="at-key"
                className="mono"
                placeholder="tradeline_mix"
                value={newType.key}
                onChange={(event) => setNewType({ ...newType, key: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="at-label">Label</Label>
              <Input
                id="at-label"
                placeholder="Tradeline mix"
                value={newType.label}
                onChange={(event) => setNewType({ ...newType, label: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1 sm:col-span-2">
              <Label htmlFor="at-desc">What the report is about</Label>
              <Input
                id="at-desc"
                placeholder="Counts by tradeline category."
                value={newType.description}
                onChange={(event) => setNewType({ ...newType, description: event.target.value })}
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                disabled={!newType.key.trim() || !newType.label.trim() || busy}
                onClick={() =>
                  void act("add the report type", async () => {
                    await api.saveArtifactType(newType);
                    setNewType({ ...NEW_TYPE });
                    setAdding(false);
                  })
                }
              >
                Add report type
              </Button>
            </div>
          </CardContent>
        ) : null}

        {!types ? (
          <Skeleton className="m-4 h-56" />
        ) : (
          <Table>
            <thead>
              <TR className="hover:bg-transparent">
                <TH>Input</TH>
                <TH>Meaning</TH>
                <TH>Enabled</TH>
                <TH />
              </TR>
            </thead>
            <tbody>
              {shownTypes.map((type) => (
                <React.Fragment key={type.key}>
                  <TR>
                    <TD>
                      <div className="flex items-center gap-2 text-sm font-medium">
                        {type.label}
                        <Badge tone="outline" title="Definition version">
                          {versionLabel(type.version)}
                        </Badge>
                      </div>
                      <div className="mono text-[0.7rem] text-muted-foreground">
                        {type.key} · {type.kind}
                        {type.is_builtin ? " · built-in" : ""}
                        {type.is_required ? " · required" : ""}
                      </div>
                    </TD>
                    <TD className="max-w-sm text-xs text-muted-foreground">
                      <div className="truncate">{type.description || "—"}</div>
                      {type.ai_context ? (
                        <Badge tone="success">AI context set</Badge>
                      ) : (
                        <span className="text-[0.7rem]">no AI context</span>
                      )}
                    </TD>
                    <TD>
                      <label className="flex items-center gap-1.5 text-xs">
                        <input
                          type="checkbox"
                          checked={type.is_active}
                          disabled={busy}
                          aria-label={`Enable ${type.label}`}
                          onChange={(event) => void save(type, { is_active: event.target.checked })}
                        />
                        {type.is_active ? "on" : "off"}
                      </label>
                    </TD>
                    <TD className="whitespace-nowrap text-right">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => setEditing(editing === type.key ? null : type.key)}
                      >
                        {editing === type.key ? "Close" : "Define"}
                      </Button>
                      {type.kind === "report" ? (
                        <Button
                          variant="ghost"
                          size="xs"
                          aria-label={`Guide for ${type.label}`}
                          onClick={() => setGuide(guide === type.key ? null : type.key)}
                        >
                          {guide === type.key ? "Hide guide" : `Guide (${type.guide.length})`}
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="xs"
                        aria-label={`Versions of ${type.label}`}
                        onClick={() => setVersions(versions === type.key ? null : type.key)}
                      >
                        {versions === type.key ? "Hide versions" : "Versions"}
                      </Button>
                      {type.is_builtin ? null : (
                        <DeleteButton
                          label={type.label}
                          busy={busy}
                          onDelete={(confirm) =>
                            act("delete the type", () => api.deleteArtifactType(type.key, confirm))
                          }
                        />
                      )}
                    </TD>
                  </TR>
                  <TR className="hover:bg-transparent">
                    <TD colSpan={4} className="bg-muted/10">
                      <SampleStrip
                        type={type}
                        busy={busy}
                        programmes={programmes}
                        onChanged={() => void load()}
                        onError={setError}
                      />
                    </TD>
                  </TR>
                  {guide === type.key ? (
                    <TR className="hover:bg-transparent">
                      <TD colSpan={4} className="bg-muted/20">
                        <GuideEditor type={type} busy={busy} onSaved={() => void load()} />
                      </TD>
                    </TR>
                  ) : null}
                  {versions === type.key ? (
                    <TR className="hover:bg-transparent">
                      <TD colSpan={4} className="bg-muted/20">
                        <VersionsPanel
                          kind="artifact-type"
                          objectKey={type.key}
                          onReverted={() => void load()}
                        />
                      </TD>
                    </TR>
                  ) : null}
                  {editing === type.key ? (
                    <TR className="hover:bg-transparent">
                      <TD colSpan={4} className="bg-muted/30">
                        <ArtifactEditor
                          type={type}
                          busy={busy}
                          onSave={(changes) => void save(type, changes)}
                        />
                      </TD>
                    </TR>
                  ) : null}
                </React.Fragment>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {group === "report" ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
          <Card>
            <CardHeader className="border-b">
              <CardTitle>Add a named value</CardTitle>
              <span className="text-[0.7rem] text-muted-foreground">
                A pointer into a report that checks refer to by name. Label lookup survives inserted
                rows; prefer it over a cell address.
              </span>
            </CardHeader>
            <CardContent className="grid gap-3 pt-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <Label htmlFor="nv-name">Name</Label>
                <Input
                  id="nv-name"
                  className="mono"
                  placeholder="billing_count"
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="nv-report">Report type</Label>
                <Select
                  id="nv-report"
                  value={draft.report_type}
                  onChange={(event) => setDraft({ ...draft, report_type: event.target.value })}
                >
                  {reportKeys.map((key) => (
                    <option key={key} value={key}>
                      {types?.find((t) => t.key === key)?.label ?? key}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="nv-sheet">Sheet</Label>
                {sheets.length > 0 ? (
                  <Select
                    id="nv-sheet"
                    value={draft.sheet}
                    onChange={(event) => setDraft({ ...draft, sheet: event.target.value })}
                  >
                    <option value="">Choose a sheet…</option>
                    {sheets.map((sheet) => (
                      <option key={sheet} value={sheet}>
                        {sheet}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input
                    id="nv-sheet"
                    placeholder="Summary"
                    value={draft.sheet}
                    onChange={(event) => setDraft({ ...draft, sheet: event.target.value })}
                  />
                )}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="nv-kind">Locator</Label>
                <Select
                  id="nv-kind"
                  value={draft.kind}
                  onChange={(event) =>
                    setDraft({ ...draft, kind: event.target.value as "label" | "cell" })
                  }
                >
                  <option value="label">Label lookup (preferred)</option>
                  <option value="cell">Cell address</option>
                </Select>
              </div>
              {draft.kind === "label" ? (
                <>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="nv-label">Label text</Label>
                    <Input
                      id="nv-label"
                      placeholder="Billing count"
                      value={draft.label}
                      onChange={(event) => setDraft({ ...draft, label: event.target.value })}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="nv-col">Value column (0-based)</Label>
                    <Input
                      id="nv-col"
                      type="number"
                      min={0}
                      value={draft.value_column}
                      onChange={(event) =>
                        setDraft({ ...draft, value_column: Number(event.target.value) })
                      }
                    />
                  </div>
                </>
              ) : (
                <div className="flex flex-col gap-1">
                  <Label htmlFor="nv-cell">Cell</Label>
                  <Input
                    id="nv-cell"
                    className="mono"
                    placeholder="H9"
                    value={draft.cell}
                    onChange={(event) => setDraft({ ...draft, cell: event.target.value })}
                  />
                </div>
              )}
              <div className="flex flex-col gap-1 sm:col-span-2">
                <Label htmlFor="nv-desc">Description</Label>
                <Input
                  id="nv-desc"
                  placeholder="Records billed to the customer for this order"
                  value={draft.description}
                  onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                />
              </div>
              <div className="sm:col-span-2">
                <Button
                  disabled={!draft.name.trim() || busy}
                  onClick={() =>
                    void act("save the named value", async () => {
                      await api.saveNamedValue(draft);
                      setDraft({ ...EMPTY_POINTER });
                    })
                  }
                >
                  Save named value
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="p-0">
            <CardHeader className="border-b">
              <CardTitle>Named values</CardTitle>
            </CardHeader>
            <div className="px-4 pt-3">
              <BulkBar
                count={selectedValues.length}
                busy={busy}
                actions={[{ word: "delete", label: "Delete selected", destructive: true }]}
                onClear={() => setSelectedValues([])}
                onAct={(confirm) =>
                  act("delete the named values", async () => {
                    await api.bulkDelete("named-values", selectedValues, confirm);
                    setSelectedValues([]);
                  })
                }
              />
            </div>
            {!values ? (
              <Skeleton className="m-4 h-32" />
            ) : values.length === 0 ? (
              <EmptyState title="No named values yet" hint="Checks refer to reports by these." />
            ) : (
              <Table>
                <thead>
                  <TR className="hover:bg-transparent">
                    <TH className="w-8" />
                    <TH>Name</TH>
                    <TH>Report · sheet</TH>
                    <TH>Resolves on sample</TH>
                    <TH>Used by</TH>
                    <TH />
                  </TR>
                </thead>
                <tbody>
                  {values.map((value) => (
                    <TR key={value.id}>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`Select ${value.name}`}
                          checked={selectedValues.includes(value.id)}
                          onChange={() =>
                            setSelectedValues((current) =>
                              current.includes(value.id)
                                ? current.filter((one) => one !== value.id)
                                : [...current, value.id]
                            )
                          }
                        />
                      </TD>
                      <TD className="mono">{value.name}</TD>
                      <TD className="text-xs">
                        {value.report_type} · {value.sheet || "—"}
                      </TD>
                      <TD>
                        {value.resolved === null ? (
                          <Badge tone="destructive">not found</Badge>
                        ) : (
                          <Badge tone="success">{value.resolved}</Badge>
                        )}
                      </TD>
                      <TD className="text-xs text-muted-foreground">
                        {value.used_by.length > 0 ? value.used_by.join(", ") : "—"}
                      </TD>
                      <TD className="text-right">
                        <DeleteButton
                          label={`named value ${value.name}`}
                          busy={busy}
                          onDelete={(confirm) =>
                            act("delete the named value", () =>
                              api.deleteNamedValue(value.id, confirm)
                            )
                          }
                        />
                      </TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}

/** The expanded editor for one artifact type's meaning and model guidance. */
function ArtifactEditor({
  type,
  busy,
  onSave,
}: {
  type: ArtifactType;
  busy: boolean;
  onSave: (changes: Partial<ArtifactType>) => void;
}) {
  const [label, setLabel] = React.useState(type.label);
  const [description, setDescription] = React.useState(type.description);
  const [context, setContext] = React.useState(type.ai_context);
  const [required, setRequired] = React.useState(type.is_required);

  return (
    <div className="grid gap-3 py-2">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`label-${type.key}`}>Label</Label>
          <Input
            id={`label-${type.key}`}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`desc-${type.key}`}>What it is, for whoever uploads it</Label>
          <Input
            id={`desc-${type.key}`}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`ctx-${type.key}`}>What the AI should look at</Label>
        <Textarea
          id={`ctx-${type.key}`}
          rows={3}
          placeholder="Leave empty and the model reads this document exactly as it does today."
          value={context}
          onChange={(event) => setContext(event.target.value)}
        />
        <span className="text-[0.7rem] text-muted-foreground">
          Passed to the model as background, never as a requirement. Requirements come only from the
          OSL.
        </span>
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={required}
            onChange={(event) => setRequired(event.target.checked)}
          />
          Required on every run
        </label>
        <Button
          disabled={busy}
          onClick={() => onSave({ label, description, ai_context: context, is_required: required })}
        >
          Save
        </Button>
      </div>
    </div>
  );
}

/** The file extension an artifact type's sample is expected to have. */
function acceptFor(kind: ArtifactType["kind"]): string {
  if (kind === "osl") return ".docx,.pdf";
  if (kind === "config") return ".json";
  return ".xlsx";
}

function sizeOf(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const MAX_SAMPLES = 3;

/**
 * Up to three samples per type. Real report layouts vary between customers, and one
 * sample averages that variation away instead of showing it (ADR-021).
 */
function SampleStrip({
  type,
  busy,
  programmes,
  onChanged,
  onError,
}: {
  type: ArtifactType;
  busy: boolean;
  programmes: Scope[] | null;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [working, setWorking] = React.useState(false);
  const [preview, setPreview] = React.useState<SamplePreview | null>(null);
  const [sheet, setSheet] = React.useState("");

  async function run(what: string, action: () => Promise<unknown>) {
    setWorking(true);
    try {
      await action();
      onChanged();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
    } finally {
      setWorking(false);
    }
  }

  async function view(sample: Sample) {
    if (preview?.sample_id === sample.id) {
      setPreview(null);
      return;
    }
    setWorking(true);
    try {
      const loaded = await api.previewSample(type.key, sample.id);
      setPreview(loaded);
      setSheet(loaded.sheets[0]?.name ?? "");
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : "Could not read the sample.");
    } finally {
      setWorking(false);
    }
  }

  const shown = preview?.sheets.find((one) => one.name === sheet) ?? preview?.sheets[0] ?? null;
  const disabled = busy || working;
  // One group per scope for the OSL and the configuration, whose layout varies by
  // programme: the global samples first, then every programme. Reports are the same
  // layouts everywhere, so they keep one flat box (every sample there is global).
  const grouped = type.kind !== "report";
  const groups: { code: string; title: string; hint: string }[] = [
    {
      code: "",
      title: grouped ? "Global" : "Samples",
      hint: grouped
        ? "Read for every programme that has no sample of its own."
        : "Named values, guides and type detection resolve against these.",
    },
    ...(grouped ? (programmes ?? []) : [])
      .filter(
        (programme) =>
          programme.is_active || type.samples.some((s) => s.scope_code === programme.code)
      )
      .map((programme) => ({
        code: programme.code,
        title: `${programme.label} (${programme.code})`,
        hint: `Read instead of the global samples on ${programme.label} runs and mappings.`,
      })),
  ];

  return (
    <div className="grid gap-2 py-1">
      {groups.map((group) => {
        const samples = type.samples.filter((s) => (s.scope_code || "") === group.code);
        return (
          <div
            key={group.code || "global"}
            className={cn(
              "rounded-md border p-2",
              group.code ? "border-l-4 border-l-primary bg-accent/10" : "bg-muted/20"
            )}
            data-testid={`samples-${type.key}-${group.code || "global"}`}
          >
            <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
              <span className="text-xs font-semibold">{group.title}</span>
              <span className="text-[0.7rem] text-muted-foreground">
                {group.hint} {samples.length} of {MAX_SAMPLES}.
              </span>
            </div>
            <div className="flex flex-wrap items-start gap-2">
              {samples.map((sample) => (
                <SampleCard
                  key={sample.id}
                  type={type}
                  sample={sample}
                  disabled={disabled}
                  previewing={preview?.sample_id === sample.id}
                  onView={() => void view(sample)}
                  onSave={(patch) =>
                    run("save the sample", () => api.updateSample(type.key, sample.id, patch))
                  }
                  onDelete={(confirm) =>
                    run("remove the sample", () => api.deleteSample(type.key, sample.id, confirm))
                  }
                />
              ))}
              {samples.length < MAX_SAMPLES ? (
                <AddSample
                  type={type}
                  scope={group.code}
                  disabled={disabled}
                  onAdd={(file, label, notes) =>
                    run("add the sample", () =>
                      api.addSample(type.key, file, label, notes, group.code)
                    )
                  }
                />
              ) : (
                <p className="self-center text-[0.7rem] text-muted-foreground">
                  Three is the limit here; remove one before adding another.
                </p>
              )}
            </div>
          </div>
        );
      })}

      {preview ? (
        <div className="mt-2 rounded-md border bg-card p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold">{preview.filename}</span>
            <Select
              className="h-7 text-xs"
              aria-label="Sheet"
              value={shown?.name ?? ""}
              onChange={(event) => setSheet(event.target.value)}
            >
              {preview.sheets.map((one) => (
                <option key={one.name} value={one.name}>
                  {one.name} ({one.rows}×{one.columns})
                </option>
              ))}
            </Select>
            <span className="text-[0.7rem] text-muted-foreground">
              Values are masked exactly as they are at parse time.
            </span>
          </div>
          {shown === null || shown.cells.length === 0 ? (
            <p className="p-2 text-xs text-muted-foreground">Nothing was read from this sheet.</p>
          ) : (
            <div className="mt-2 max-h-80 overflow-y-auto">
              <Table>
                <thead>
                  <TR className="hover:bg-transparent">
                    <TH>Cell</TH>
                    <TH>Label</TH>
                    <TH>Value</TH>
                  </TR>
                </thead>
                <tbody>
                  {shown.cells.map((cell) => (
                    <TR key={cell.cell}>
                      <TD className="mono text-xs">{cell.cell}</TD>
                      <TD className="text-xs text-muted-foreground">{cell.label || "—"}</TD>
                      <TD className="text-xs">{cell.value}</TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** One stored sample: what it is, its notes, view / download / edit / delete. */
function SampleCard({
  type,
  sample,
  disabled,
  previewing,
  onView,
  onSave,
  onDelete,
}: {
  type: ArtifactType;
  sample: Sample;
  disabled: boolean;
  previewing: boolean;
  onView: () => void;
  onSave: (patch: { label?: string; notes?: string }) => void;
  onDelete: (confirm: string) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [label, setLabel] = React.useState(sample.label);
  const [notes, setNotes] = React.useState(sample.notes);

  return (
    <div className="min-w-[15rem] max-w-sm rounded-md border bg-card p-2">
      {editing ? (
        <div className="grid gap-1">
          <Label htmlFor={`sl-${sample.id}`}>Label</Label>
          <Input
            id={`sl-${sample.id}`}
            className="h-7 text-xs"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
          <Label htmlFor={`sn-${sample.id}`}>Notes for the model and the team</Label>
          <Textarea
            id={`sn-${sample.id}`}
            rows={3}
            className="text-xs"
            placeholder="How this variant differs; what to look for in it."
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
          <div className="flex gap-1">
            <Button
              size="xs"
              disabled={disabled}
              onClick={() => {
                onSave({ label: label.trim(), notes: notes.trim() });
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div className="text-xs font-semibold">{sample.label || sample.filename}</div>
          <div
            className="mono truncate text-[0.7rem] text-muted-foreground"
            title={sample.filename}
          >
            {sample.filename} · {sizeOf(sample.size_bytes)}
          </div>
          <div className="mt-0.5 text-[0.7rem] text-muted-foreground">
            {sample.sheets.length > 0
              ? sample.sheets.join(", ")
              : type.kind === "report"
                ? "no sheets read"
                : type.kind === "osl"
                  ? "Word or PDF, read section by section"
                  : "JSON, read block by block"}
          </div>
          {sample.notes ? (
            <p className="mt-1 whitespace-pre-wrap text-[0.7rem]">{sample.notes}</p>
          ) : (
            <p className="mt-1 text-[0.7rem] italic text-muted-foreground">
              No notes yet. Notes reach the model when it maps this scope.
            </p>
          )}
          <div className="text-[0.7rem] text-muted-foreground">
            uploaded by {sample.uploaded_by || "—"}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Button variant="outline" size="xs" disabled={disabled} onClick={onView}>
              <Eye className="h-3.5 w-3.5" />
              {previewing ? "Hide" : "View"}
            </Button>
            {/* A plain link, so the browser streams the workbook to disk rather than
                the page holding the whole file in memory. */}
            <a
              href={api.sampleDownloadUrl(type.key, sample.id)}
              download={sample.filename}
              className="inline-flex h-6 items-center gap-1.5 rounded-md border bg-card px-2 text-[0.7rem] font-medium hover:bg-accent"
            >
              <Download className="h-3.5 w-3.5" /> Download
            </a>
            <Button variant="ghost" size="xs" disabled={disabled} onClick={() => setEditing(true)}>
              Edit
            </Button>
            <DeleteButton
              label={`sample ${sample.label || sample.filename}`}
              busy={disabled}
              onDelete={onDelete}
            />
          </div>
        </>
      )}
    </div>
  );
}

/** The add form for one scope: a label, notes, and the file. */
function AddSample({
  type,
  scope,
  disabled,
  onAdd,
}: {
  type: ArtifactType;
  scope: string;
  disabled: boolean;
  onAdd: (file: File, label: string, notes: string) => void;
}) {
  const [label, setLabel] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const id = `${type.key}-${scope || "global"}`;

  return (
    <div className="min-w-[13rem] max-w-sm rounded-md border border-dashed p-2">
      <Label htmlFor={`sample-label-${id}`}>Label</Label>
      <Input
        id={`sample-label-${id}`}
        className="mt-1 h-7 text-xs"
        placeholder="what tells it apart"
        value={label}
        onChange={(event) => setLabel(event.target.value)}
      />
      <Label htmlFor={`sample-notes-${id}`} className="mt-1.5 block">
        Notes
      </Label>
      <Textarea
        id={`sample-notes-${id}`}
        rows={2}
        className="mt-1 text-xs"
        placeholder="How this variant differs; what the model should know about it."
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />
      <input
        ref={fileInput}
        type="file"
        accept={acceptFor(type.kind)}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          onAdd(file, label.trim(), notes.trim());
          setLabel("");
          setNotes("");
        }}
      />
      <Button
        className="mt-1.5"
        variant="outline"
        size="xs"
        disabled={disabled}
        onClick={() => fileInput.current?.click()}
      >
        <Upload className="h-3.5 w-3.5" /> Add {scope ? `for ${scope}` : "global"} sample
      </Button>
    </div>
  );
}

"use client";

/**
 * Artifact types: what the tool accepts, what each one means, and what the model
 * should look at in it (ADR-020).
 *
 * Everything here is optional. A type with no description and no guidance behaves
 * exactly as it did before this screen existed, which is why the guidance field says
 * so rather than looking like a required setting.
 */

import { Plus, Trash2, Upload } from "lucide-react";
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
import { api, ApiError } from "@/lib/api";
import type { ArtifactType, NamedValue } from "@/lib/types";

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

export default function ArtifactsPage() {
  const [types, setTypes] = React.useState<ArtifactType[] | null>(null);
  const [values, setValues] = React.useState<NamedValue[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [newType, setNewType] = React.useState({ ...NEW_TYPE });
  const [draft, setDraft] = React.useState({ ...EMPTY_POINTER });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [nextTypes, nextValues] = await Promise.all([
        api.listArtifactTypes(),
        api.listNamedValues(),
      ]);
      setTypes(nextTypes);
      setValues(nextValues);
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

      <Card className="mb-4 p-0">
        <CardHeader className="flex-row items-center justify-between border-b">
          <div>
            <CardTitle>Inputs</CardTitle>
            <span className="text-[0.7rem] text-muted-foreground">
              Switching a type off removes its upload slot for every user, at once.
            </span>
          </div>
          <Button size="xs" variant="outline" onClick={() => setAdding(!adding)}>
            <Plus className="h-3.5 w-3.5" /> Add a report type
          </Button>
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
                <TH>Sample</TH>
                <TH>Enabled</TH>
                <TH />
              </TR>
            </thead>
            <tbody>
              {types.map((type) => (
                <React.Fragment key={type.key}>
                  <TR>
                    <TD>
                      <div className="text-sm font-medium">{type.label}</div>
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
                    <TD className="text-xs text-muted-foreground">
                      {type.has_sample ? (
                        <span className="truncate">
                          {type.filename} · {type.sheets.join(", ") || "no sheets read"}
                        </span>
                      ) : (
                        "—"
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
                      <label>
                        <span className="sr-only">Upload a sample for {type.label}</span>
                        <input
                          type="file"
                          accept={
                            type.kind === "osl"
                              ? ".docx"
                              : type.kind === "config"
                                ? ".json"
                                : ".xlsx"
                          }
                          className="hidden"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file)
                              void act("upload the sample", () => api.uploadSample(type.key, file));
                          }}
                        />
                        <span className="mr-1 inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border bg-card px-2.5 text-xs font-medium hover:bg-accent">
                          <Upload className="h-3.5 w-3.5" />
                          {type.has_sample ? "Replace" : "Sample"}
                        </span>
                      </label>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => setEditing(editing === type.key ? null : type.key)}
                      >
                        {editing === type.key ? "Close" : "Define"}
                      </Button>
                      {type.is_builtin ? null : (
                        <Button
                          variant="ghost"
                          size="xs"
                          disabled={busy}
                          aria-label={`Delete ${type.label}`}
                          onClick={() =>
                            void act("delete the type", () => api.deleteArtifactType(type.key))
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </TD>
                  </TR>
                  {editing === type.key ? (
                    <TR className="hover:bg-transparent">
                      <TD colSpan={5} className="bg-muted/30">
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
          {!values ? (
            <Skeleton className="m-4 h-32" />
          ) : values.length === 0 ? (
            <EmptyState title="No named values yet" hint="Checks refer to reports by these." />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
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
                      <Button
                        variant="ghost"
                        size="xs"
                        disabled={busy}
                        aria-label={`Delete ${value.name}`}
                        onClick={() =>
                          void act("delete the named value", () => api.deleteNamedValue(value.id))
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
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

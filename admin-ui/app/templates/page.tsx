"use client";

/**
 * Report templates and named values.
 *
 * A named value is a pointer into a report. The screen shows what each one resolves to
 * on the uploaded sample, because a pointer that no longer finds anything is the
 * failure this screen exists to catch.
 */

import { CheckCircle2, Trash2, Upload, XCircle } from "lucide-react";
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
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { REPORT_KINDS, REPORT_LABELS, type NamedValue, type Template } from "@/lib/types";

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

export default function TemplatesPage() {
  const [templates, setTemplates] = React.useState<Template[] | null>(null);
  const [values, setValues] = React.useState<NamedValue[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState({ ...EMPTY_POINTER });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [nextTemplates, nextValues] = await Promise.all([
        api.listTemplates(),
        api.listNamedValues(),
      ]);
      setTemplates(nextTemplates);
      setValues(nextValues);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function upload(reportType: string, file: File) {
    setBusy(true);
    try {
      await api.uploadTemplate(reportType, file);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not upload the template.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    try {
      await api.saveNamedValue(draft);
      setDraft({ ...EMPTY_POINTER });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the named value.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(value: NamedValue) {
    setBusy(true);
    try {
      await api.deleteNamedValue(value.id);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not delete the named value.");
    } finally {
      setBusy(false);
    }
  }

  const sheets = templates?.find((t) => t.report_type === draft.report_type)?.sheets ?? [];

  return (
    <>
      <PageHeader
        title="Report templates & named values"
        description="One sample workbook per report type documents where values live. A named value is a pointer into a report that checks refer to by name."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
        <Card>
          <CardHeader className="border-b">
            <CardTitle>Report types</CardTitle>
          </CardHeader>
          <CardContent className="pt-3">
            {!templates ? (
              <Skeleton className="h-40" />
            ) : (
              <div className="flex flex-col gap-1.5">
                {REPORT_KINDS.map((kind) => {
                  const template = templates.find((t) => t.report_type === kind);
                  return (
                    <div
                      key={kind}
                      className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-2"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{REPORT_LABELS[kind]}</div>
                        <div className="truncate text-[0.7rem] text-muted-foreground">
                          {template
                            ? `${template.filename} · ${template.sheets.join(", ") || "no sheets read"}`
                            : "No sample uploaded"}
                        </div>
                      </div>
                      <label className="flex-shrink-0">
                        <span className="sr-only">Upload a sample for {REPORT_LABELS[kind]}</span>
                        <input
                          type="file"
                          accept=".xlsx"
                          className="hidden"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void upload(kind, file);
                          }}
                        />
                        <span className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border bg-card px-3 text-xs font-medium hover:bg-accent">
                          <Upload className="h-3.5 w-3.5" />
                          {template ? "Replace" : "Upload"}
                        </span>
                      </label>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="border-b">
              <CardTitle>Add a named value</CardTitle>
              <span className="text-[0.7rem] text-muted-foreground">
                Label lookup survives inserted rows; prefer it over a cell address.
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
                  {REPORT_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {REPORT_LABELS[kind]}
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
                <Button disabled={!draft.name.trim() || busy} onClick={() => void save()}>
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
                    <TH>Locator</TH>
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
                      <TD className="text-xs">
                        {value.kind === "cell" ? (
                          <span className="mono">{value.cell}</span>
                        ) : (
                          <>
                            <Badge tone="muted">label</Badge>{" "}
                            <span className="text-muted-foreground">
                              “{value.label}” → col {value.value_column}
                            </span>
                          </>
                        )}
                      </TD>
                      <TD>
                        {value.resolved === null ? (
                          <Badge tone="destructive">
                            <XCircle className="h-3 w-3" /> not found
                          </Badge>
                        ) : (
                          <Badge tone="success">
                            <CheckCircle2 className="h-3 w-3" /> {value.resolved}
                          </Badge>
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
                          onClick={() => void remove(value)}
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
      </div>
    </>
  );
}

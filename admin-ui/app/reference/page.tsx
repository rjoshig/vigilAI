"use client";

/**
 * Reference data: attribute aliases and masked columns.
 *
 * Aliases are what let an OSL that says "score" match a report column called
 * `SCORE_V3`. Masked columns are applied at parse time, so an unmasked value never
 * exists downstream (ADR-003).
 */

import { EyeOff, Trash2 } from "lucide-react";
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
  Skeleton,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Alias, MaskedColumn } from "@/lib/types";

export default function ReferencePage() {
  const [aliases, setAliases] = React.useState<Alias[] | null>(null);
  const [masked, setMasked] = React.useState<MaskedColumn[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [aliasDraft, setAliasDraft] = React.useState({
    canonical_name: "",
    alias: "",
    customer: "",
  });
  const [patternDraft, setPatternDraft] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const [nextAliases, nextMasked] = await Promise.all([
        api.listAliases(),
        api.listMaskedColumns(),
      ]);
      setAliases(nextAliases);
      setMasked(nextMasked);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const grouped = (aliases ?? []).reduce<Record<string, Alias[]>>((acc, alias) => {
    (acc[alias.canonical_name] ??= []).push(alias);
    return acc;
  }, {});

  return (
    <>
      <PageHeader
        title="Reference data"
        description="Attribute aliases map field names across the OSL, the config, and the reports. Masked columns are hidden everywhere: the app, the report, and the PDF."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card className="p-0">
          <CardHeader className="border-b">
            <CardTitle>Attribute aliases</CardTitle>
            <span className="text-[0.7rem] text-muted-foreground">
              Without an alias, a check on “score” cannot find a column called SCORE_V3.
            </span>
          </CardHeader>
          {!aliases ? (
            <Skeleton className="m-4 h-32" />
          ) : aliases.length === 0 ? (
            <EmptyState
              title="No aliases yet"
              hint="Add one when a run reports that a value could not be evaluated."
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH>Canonical name</TH>
                  <TH>Aliases</TH>
                  <TH>Customer</TH>
                </TR>
              </thead>
              <tbody>
                {Object.entries(grouped).map(([canonical, entries]) => (
                  <TR key={canonical}>
                    <TD className="mono">{canonical}</TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {entries.map((entry) => (
                          <span
                            key={entry.id}
                            className="mono inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-0.5 text-[0.7rem]"
                          >
                            {entry.alias}
                            <button
                              type="button"
                              aria-label={`Delete alias ${entry.alias}`}
                              className="text-muted-foreground hover:text-destructive"
                              onClick={async () => {
                                await api.deleteAlias(entry.id);
                                await load();
                              }}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {entries[0].customer_name ?? "All"}
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
          <CardContent className="grid gap-3 border-t pt-4 sm:grid-cols-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor="canonical">Canonical name</Label>
              <Input
                id="canonical"
                className="mono"
                placeholder="score"
                value={aliasDraft.canonical_name}
                onChange={(event) =>
                  setAliasDraft({ ...aliasDraft, canonical_name: event.target.value })
                }
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="alias">Alias</Label>
              <Input
                id="alias"
                className="mono"
                placeholder="SCORE_V3"
                value={aliasDraft.alias}
                onChange={(event) => setAliasDraft({ ...aliasDraft, alias: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="alias-customer">Customer (blank = all)</Label>
              <Input
                id="alias-customer"
                value={aliasDraft.customer}
                onChange={(event) => setAliasDraft({ ...aliasDraft, customer: event.target.value })}
              />
            </div>
            <div className="flex items-end">
              <Button
                disabled={!aliasDraft.canonical_name.trim() || !aliasDraft.alias.trim() || busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.createAlias({
                      canonical_name: aliasDraft.canonical_name.trim(),
                      alias: aliasDraft.alias.trim(),
                      customer_name: aliasDraft.customer.trim() || null,
                    });
                    setAliasDraft({ canonical_name: "", alias: "", customer: "" });
                    await load();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Add alias
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b">
            <CardTitle className="flex items-center gap-1.5">
              <EyeOff className="h-4 w-4 text-primary" /> Masked columns
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-3">
            <p className="mb-3 text-xs text-muted-foreground">
              Matched against report column names. A trailing <span className="mono">*</span> makes
              it a prefix. There is no unmask control in v1.
            </p>

            {!masked ? (
              <Skeleton className="h-32" />
            ) : (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {masked.map((column) => (
                  <span
                    key={`${column.id}-${column.pattern}`}
                    className="mono inline-flex items-center gap-1 rounded border bg-card px-1.5 py-0.5 text-[0.7rem]"
                  >
                    {column.pattern}
                    {column.is_default ? (
                      <Badge tone="muted" className="ml-0.5">
                        default
                      </Badge>
                    ) : (
                      <button
                        type="button"
                        aria-label={`Remove ${column.pattern}`}
                        className="text-muted-foreground hover:text-destructive"
                        onClick={async () => {
                          await api.deleteMaskedColumn(column.id);
                          await load();
                        }}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </span>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <Input
                placeholder="ACCT_*"
                className="mono"
                aria-label="New masked column pattern"
                value={patternDraft}
                onChange={(event) => setPatternDraft(event.target.value)}
              />
              <Button
                disabled={!patternDraft.trim() || busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.createMaskedColumn(patternDraft.trim());
                    setPatternDraft("");
                    await load();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Add
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

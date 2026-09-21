"use client";

/**
 * Reference data: what a delivery calls a checked field, attribute aliases, and
 * masked columns.
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
import { useAuth } from "@/components/auth-gate";
import { BulkBar } from "@/components/bulk-bar";
import { FieldEffect } from "@/components/explain";
import { FieldLabelsCard } from "@/components/field-labels-card";
import { DeleteButton } from "@/components/confirm-delete";
import { api, ApiError } from "@/lib/api";
import type { Alias, MaskedColumn, Scope } from "@/lib/types";

export default function ReferencePage() {
  // A reviewer keeps the aliases and the field labels -- knowing what a delivery calls
  // a field is part of judging one -- but not the masked columns, which are the single
  // control that keeps personal data out of every prompt (ADR-003, ADR-049). The card
  // goes rather than the screen: hiding the whole screen would take a reviewer's own
  // work away to protect one card on it.
  const { can } = useAuth();
  const maySeeMasked = can("manage_privacy");
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
  const [selected, setSelected] = React.useState<number[]>([]);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [nextAliases, nextMasked, nextProgrammes] = await Promise.all([
        api.listAliases(),
        // Not even asked for without the capability: the API would answer 403 and the
        // screen would report a failure for something it was never going to show.
        maySeeMasked ? api.listMaskedColumns() : Promise.resolve([]),
        api.listScopes(),
      ]);
      setAliases(nextAliases);
      setMasked(nextMasked);
      setProgrammes(nextProgrammes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [maySeeMasked]);

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
        description="What a delivery calls the fields the tool checks, the aliases that map attribute names across the OSL, the config and the reports, and the columns masked everywhere: the app, the report, and the PDF."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="mb-4">
        <FieldLabelsCard programmes={programmes} onError={setError} />
      </div>

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
            <>
              <BulkBar
                count={selected.length}
                busy={busy}
                actions={[{ word: "delete", label: "Delete selected aliases", destructive: true }]}
                onClear={() => setSelected([])}
                onAct={async (confirm) => {
                  await api.bulkDelete("aliases", selected, confirm);
                  setSelected([]);
                  await load();
                }}
              />
              <Table>
                <thead>
                  <TR className="hover:bg-transparent">
                    <TH className="w-8" />
                    <TH>Canonical name</TH>
                    <TH>Aliases</TH>
                    <TH>Customer</TH>
                  </TR>
                </thead>
                <tbody>
                  {Object.entries(grouped).map(([canonical, entries]) => (
                    <TR key={canonical}>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`Select every alias of ${canonical}`}
                          checked={entries.every((entry) => selected.includes(entry.id))}
                          onChange={(event) => {
                            const ids = entries.map((entry) => entry.id);
                            setSelected((current) =>
                              event.target.checked
                                ? [...current, ...ids.filter((id) => !current.includes(id))]
                                : current.filter((id) => !ids.includes(id))
                            );
                          }}
                        />
                      </TD>
                      <TD className="mono">{canonical}</TD>
                      <TD>
                        <div className="flex flex-wrap gap-1">
                          {entries.map((entry) => (
                            <span
                              key={entry.id}
                              className="mono inline-flex items-center gap-1 rounded border bg-muted px-1.5 py-0.5 text-[0.7rem]"
                            >
                              {entry.alias}
                              <DeleteButton
                                compact
                                label={`alias ${entry.alias}`}
                                busy={busy}
                                onDelete={async (confirm) => {
                                  await api.deleteAlias(entry.id, confirm);
                                  await load();
                                }}
                              />
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
            </>
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

        {maySeeMasked ? (
          <Card>
            <CardHeader className="border-b">
              <CardTitle className="flex items-center gap-1.5">
                <EyeOff className="h-4 w-4 text-primary" /> Masked columns
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-3">
              <p className="mb-3 text-xs text-muted-foreground">
                Matched against report column names. A trailing <span className="mono">*</span>{" "}
                makes it a prefix. There is no unmask control in v1.
              </p>
              <FieldEffect
                kind="code"
                className="mb-3"
                note="This list is what keeps personal data out of every prompt. A column named here is replaced as the workbook is read, so an unmasked value never exists downstream — not in a prompt, not in a log, not in the database. Naming a column here is the strongest control you have."
              />

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
                        <DeleteButton
                          compact
                          label={`masked column ${column.pattern}`}
                          busy={busy}
                          onDelete={async (confirm) => {
                            await api.deleteMaskedColumn(column.id, confirm);
                            await load();
                          }}
                        />
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
        ) : null}
      </div>
    </>
  );
}

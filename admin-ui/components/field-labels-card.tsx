"use client";

/**
 * What this delivery calls the fields the tool checks (Phase 6.14b, ADR-041).
 *
 * A delivery is cut as of a date, and the reports say so in a cell. What that cell is
 * *called* varies with whoever built the workbook: "as-of date", "data date", "cycle
 * date", "extract date". Teaching the tool the spelling turns a search for the date's
 * value — which could say "this date appears nowhere" and nothing more — into a
 * comparison that can say "the reports are cut as of 2026-03-31, not the 2026-04-30 you
 * gave".
 *
 * The spellings the tool ships with are listed first and read-only. They are not rows
 * in the table: a deployment that adds none still checks with them, so this screen can
 * be ignored entirely and nothing is worse than it was.
 */

import { Plus } from "lucide-react";
import * as React from "react";

import { Explain, FieldEffect } from "@/components/explain";
import { ScopePicker } from "@/components/scope-picker";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  Label,
  Select,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { DeleteButton } from "@/components/confirm-delete";
import { api, ApiError } from "@/lib/api";
import type { FieldLabel, Scope } from "@/lib/types";

/** The fields the tool checks, and how each is named on screen. */
const CANONICAL: Record<string, string> = {
  credit_date: "Credit date",
};

export function FieldLabelsCard({
  programmes,
  onError,
}: {
  programmes: Scope[] | null;
  onError: (message: string) => void;
}) {
  const [labels, setLabels] = React.useState<FieldLabel[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [draft, setDraft] = React.useState({
    canonical: "credit_date",
    label: "",
    scope: "everywhere",
  });

  const load = React.useCallback(async () => {
    try {
      setLabels(await api.listFieldLabels());
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : "Could not read the labels.");
    }
  }, [onError]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      await load();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
    } finally {
      setBusy(false);
    }
  }

  const builtin = (labels ?? []).filter((row) => row.is_builtin);
  const configured = (labels ?? []).filter((row) => !row.is_builtin);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1">
          What a delivery calls a checked field
          <Explain label="What field labels are for">
            The tool compares the credit date on the form with the date the reports say they are cut
            as of. To read that date it has to find the cell, and different customers label it
            differently.
            <br />
            <br />
            Add the spelling this delivery uses. Scope it to a programme or one configuration if
            only they use it. Add nothing and the built-in spellings below still apply — this screen
            only ever makes the check better.
            <br />
            <br />
            Not to be confused with <b>aliases</b> below, which map the names a{" "}
            <i>data attribute</i> goes by. These name a label in a document.
          </Explain>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-4 grid gap-2 sm:grid-cols-[10rem,1fr,14rem,auto] sm:items-end">
          <div className="flex flex-col gap-1">
            <Label htmlFor="fl-canonical">Field</Label>
            <Select
              id="fl-canonical"
              value={draft.canonical}
              onChange={(event) => setDraft({ ...draft, canonical: event.target.value })}
            >
              {Object.entries(CANONICAL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="fl-label">What this delivery calls it</Label>
            <Input
              id="fl-label"
              value={draft.label}
              placeholder="Cycle date"
              onChange={(event) => setDraft({ ...draft, label: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label>Where it applies</Label>
            <ScopePicker
              idPrefix="fl-scope"
              value={draft.scope}
              programmes={programmes}
              onChange={(scope) => setDraft({ ...draft, scope })}
            />
          </div>
          <Button
            disabled={busy || !draft.label.trim()}
            onClick={() =>
              void act("add the label", async () => {
                await api.createFieldLabel({
                  canonical: draft.canonical,
                  label: draft.label.trim(),
                  scope: draft.scope,
                });
                setDraft({ ...draft, label: "" });
              })
            }
          >
            <Plus className="mr-1 h-4 w-4" aria-hidden />
            Add
          </Button>
        </div>

        <FieldEffect
          kind="code"
          note="Code reads the labelled cell and compares its value with the date on the form, before the model is asked anything."
          className="mb-3"
        />

        {configured.length === 0 ? (
          <EmptyState
            title="No labels of your own yet"
            hint="The built-in spellings below are in force, so the check works without this screen."
          />
        ) : (
          <Table>
            <thead>
              <TR>
                <TH>Field</TH>
                <TH>Label</TH>
                <TH>Where</TH>
                <TH>Added by</TH>
                <TH aria-label="Actions" />
              </TR>
            </thead>
            <tbody>
              {configured.map((row) => (
                <TR key={row.id} className={row.is_active ? "" : "opacity-50"}>
                  <TD>{CANONICAL[row.canonical] ?? row.canonical}</TD>
                  <TD className="mono">{row.label}</TD>
                  <TD>{row.scope_label || row.scope}</TD>
                  <TD className="text-xs text-muted-foreground">{row.created_by}</TD>
                  <TD className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        void act("change the label", () =>
                          api.setFieldLabelActive(row.id, !row.is_active)
                        )
                      }
                    >
                      {row.is_active ? "Switch off" : "Switch on"}
                    </Button>
                    <DeleteButton
                      compact
                      label={`the label ${row.label}`}
                      busy={busy}
                      onDelete={async (confirm) => {
                        await api.deleteFieldLabel(row.id, confirm);
                        await load();
                      }}
                    />
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}

        <div className="mt-4">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Always in force, whatever you add:
          </p>
          <div className="flex flex-wrap gap-1">
            {builtin.map((row) => (
              <Badge key={`${row.canonical}-${row.label}`} tone="muted">
                {row.label}
              </Badge>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

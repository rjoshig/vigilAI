"use client";

/**
 * Compliance rules and reverse-pass scope.
 *
 * Compliance rules work the other way round from OSL requirements: each one must be
 * present in the config even if the OSL never mentions it. The reverse pass is scoped,
 * not exhaustive, because the OSL does not describe every detail of the extract
 * process (`docs/design.md` "Processing pipeline", step 6).
 */

import * as React from "react";

import { Explain } from "@/components/explain";
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
import { BulkBar } from "@/components/bulk-bar";
import { DeleteButton } from "@/components/confirm-delete";
import { EVERYWHERE, ScopePicker, scopeIsComplete, scopeLabel } from "@/components/scope-picker";
import { api, ApiError } from "@/lib/api";
import type { Category, ComplianceRule, Scope } from "@/lib/types";

export default function CompliancePage() {
  const [rules, setRules] = React.useState<ComplianceRule[] | null>(null);
  const [categories, setCategories] = React.useState<Category[] | null>(null);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);
  const [selected, setSelected] = React.useState<number[]>([]);
  const [editing, setEditing] = React.useState<ComplianceRule | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [draft, setDraft] = React.useState({
    name: "",
    json_path_contains: "",
    alternates: "",
    reasoning: "",
    scope: EVERYWHERE,
  });

  const load = React.useCallback(async () => {
    try {
      const [nextRules, nextCategories, nextProgrammes] = await Promise.all([
        api.listComplianceRules(),
        api.listCategories(),
        api.listScopes(),
      ]);
      setRules(nextRules);
      setCategories(nextCategories);
      setProgrammes(nextProgrammes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function addRule() {
    setBusy(true);
    try {
      await api.saveComplianceRule({
        name: draft.name.trim(),
        json_path_contains: draft.json_path_contains.trim(),
        alternates: draft.alternates
          .split(/[\n,]/)
          .map((p) => p.trim())
          .filter(Boolean),
        expected_value: true,
        scope: draft.scope,
        reasoning: draft.reasoning,
        is_active: true,
      });
      setDraft({
        name: "",
        json_path_contains: "",
        alternates: "",
        reasoning: "",
        scope: EVERYWHERE,
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the rule.");
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    if (!editing) return;
    setBusy(true);
    try {
      await api.updateComplianceRule(editing.id, {
        name: editing.name.trim(),
        json_path_contains: editing.json_path_contains.trim(),
        alternates: editing.alternates ?? [],
        expected_value: editing.expected_value,
        scope: editing.scope,
        reasoning: editing.reasoning,
        is_active: editing.is_active,
      });
      setEditing(null);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the rule.");
    } finally {
      setBusy(false);
    }
  }

  function toggleSelected(id: number) {
    setSelected((current) =>
      current.includes(id) ? current.filter((one) => one !== id) : [...current, id]
    );
  }

  async function toggleCategory(category: Category) {
    setBusy(true);
    try {
      await api.saveCategory({
        name: category.name,
        kinds: category.kinds,
        checked: !category.checked,
      });
      await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        explain={
          <Explain label="What compliance rules are for">
            A compliance rule asks whether the configuration <i>implements</i> something — an
            opt-out list applied, a suppression in place. Code looks for it at a JSON path and
            reports when it is absent.
            <br />
            <br />
            Not here: a rule about a <i>report&rsquo;s values</i> is a <b>check</b>; a rule the
            model reads and grades is a <b>programme rule</b>.
          </Explain>
        }
        title="Compliance & scope"
        description="Compliance rules must be present in every config in scope, even when the OSL never mentions them. Reverse-pass categories decide which config elements are checked back against the OSL. Evaluated by code on every run; nothing here is sent to the model."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <Card className="mb-4 p-0">
        <CardHeader className="border-b">
          <CardTitle>Must-have compliance rules</CardTitle>
          <span className="text-[0.7rem] text-muted-foreground">
            A missing rule becomes a high-severity finding on every run in scope.
          </span>
        </CardHeader>
        {!rules ? (
          <Skeleton className="m-4 h-24" />
        ) : rules.length === 0 ? (
          <EmptyState title="No compliance rules yet" />
        ) : (
          <>
            <div className="px-4 pt-3">
              <BulkBar
                count={selected.length}
                busy={busy}
                actions={[{ word: "delete", label: "Delete selected", destructive: true }]}
                onClear={() => setSelected([])}
                onAct={async (confirm) => {
                  setBusy(true);
                  try {
                    await api.bulkDelete("compliance-rules", selected, confirm);
                    setSelected([]);
                    await load();
                  } finally {
                    setBusy(false);
                  }
                }}
              />
            </div>
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH className="w-8" />
                  <TH>Name</TH>
                  <TH>Config path must contain</TH>
                  <TH>Scope</TH>
                  <TH>Reasoning</TH>
                  <TH />
                </TR>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <React.Fragment key={rule.id}>
                    <TR>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`Select ${rule.name}`}
                          checked={selected.includes(rule.id)}
                          onChange={() => toggleSelected(rule.id)}
                        />
                      </TD>
                      <TD className="font-semibold">
                        {rule.name}{" "}
                        <Badge tone="outline" title="Version">
                          v{rule.version}
                        </Badge>
                      </TD>
                      <TD className="mono text-xs">
                        {rule.json_path_contains}
                        {rule.alternates?.length ? (
                          <span className="block text-muted-foreground">
                            or {rule.alternates.join(", ")}
                          </span>
                        ) : null}
                      </TD>
                      <TD className="text-xs">{scopeLabel(rule.scope, programmes)}</TD>
                      <TD className="text-xs text-muted-foreground">{rule.reasoning || "—"}</TD>
                      <TD className="whitespace-nowrap text-right">
                        <Button
                          variant="ghost"
                          size="xs"
                          disabled={busy}
                          onClick={() => setEditing(editing?.id === rule.id ? null : { ...rule })}
                        >
                          {editing?.id === rule.id ? "Close" : "Edit"}
                        </Button>{" "}
                        <DeleteButton
                          label={rule.name}
                          busy={busy}
                          onDelete={async (confirm) => {
                            await api.deleteComplianceRule(rule.id, confirm);
                            await load();
                          }}
                        />
                      </TD>
                    </TR>
                    {editing?.id === rule.id ? (
                      <TR className="hover:bg-transparent">
                        <TD colSpan={6} className="bg-muted/30">
                          <div className="grid gap-3 py-2 sm:grid-cols-3">
                            <div className="flex flex-col gap-1">
                              <Label htmlFor={`ce-name-${rule.id}`}>Name</Label>
                              <Input
                                id={`ce-name-${rule.id}`}
                                value={editing.name}
                                onChange={(event) =>
                                  setEditing({ ...editing, name: event.target.value })
                                }
                              />
                            </div>
                            <div className="flex flex-col gap-1">
                              <Label htmlFor={`ce-path-${rule.id}`}>Config path contains</Label>
                              <Input
                                id={`ce-path-${rule.id}`}
                                className="mono"
                                value={editing.json_path_contains}
                                onChange={(event) =>
                                  setEditing({ ...editing, json_path_contains: event.target.value })
                                }
                              />
                            </div>
                            <div className="flex flex-col gap-1">
                              <Label htmlFor={`ce-reason-${rule.id}`}>Reasoning</Label>
                              <Input
                                id={`ce-reason-${rule.id}`}
                                value={editing.reasoning}
                                onChange={(event) =>
                                  setEditing({ ...editing, reasoning: event.target.value })
                                }
                              />
                            </div>
                            <div className="sm:col-span-2">
                              <ScopePicker
                                idPrefix={`ce-${rule.id}`}
                                value={editing.scope}
                                programmes={programmes}
                                disabled={busy}
                                onChange={(scope) => setEditing({ ...editing, scope })}
                              />
                            </div>
                            <div className="flex items-end gap-2">
                              <Button
                                disabled={
                                  busy || !editing.name.trim() || !editing.json_path_contains.trim()
                                }
                                onClick={() => void saveEdit()}
                              >
                                Save (becomes v{rule.version + 1})
                              </Button>
                            </div>
                          </div>
                        </TD>
                      </TR>
                    ) : null}
                  </React.Fragment>
                ))}
              </tbody>
            </Table>
          </>
        )}
        <CardContent className="grid gap-3 border-t pt-4 sm:grid-cols-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="cr-name">Name</Label>
            <Input
              id="cr-name"
              placeholder="OFAC suppression"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="cr-path">Config path</Label>
            <Input
              id="cr-path"
              className="mono"
              placeholder="suppressions.ofac"
              value={draft.json_path_contains}
              onChange={(event) => setDraft({ ...draft, json_path_contains: event.target.value })}
            />
            <span className="text-[0.7rem] text-muted-foreground">
              A different spelling and an extra level of nesting are allowed for:
              <span className="mono"> opt_out</span> finds <span className="mono">optout</span>, and
              a control grouped under a <span className="mono">lists</span> key is still found.
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="cr-alts">Also implemented at (optional)</Label>
            <Input
              id="cr-alts"
              className="mono"
              placeholder="suppressions.sdn_screening, exclusions.ofac"
              value={draft.alternates}
              onChange={(event) => setDraft({ ...draft, alternates: event.target.value })}
            />
            <span className="text-[0.7rem] text-muted-foreground">
              For the case no amount of normalising reaches — a customer whose OFAC screening is
              called something else entirely. One per line, or comma-separated.
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="cr-reason">Reasoning</Label>
            <Input
              id="cr-reason"
              placeholder="OFAC-listed consumers must be suppressed on every delivery."
              value={draft.reasoning}
              onChange={(event) => setDraft({ ...draft, reasoning: event.target.value })}
            />
          </div>
          <div className="sm:col-span-3">
            <ScopePicker
              idPrefix="cr"
              value={draft.scope}
              programmes={programmes}
              disabled={busy}
              onChange={(scope) => setDraft({ ...draft, scope })}
            />
            <p className="mt-1 text-[0.7rem] text-muted-foreground">
              A rule scoped to a programme is checked only on runs of that programme; one scoped to
              a customer only on that customer&apos;s runs.
            </p>
          </div>
          <div className="flex items-end">
            <Button
              disabled={
                !draft.name.trim() ||
                !draft.json_path_contains.trim() ||
                !scopeIsComplete(draft.scope) ||
                busy
              }
              onClick={() => void addRule()}
            >
              Add rule
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="p-0">
        <CardHeader className="border-b">
          <CardTitle>Reverse-pass categories</CardTitle>
          <span className="text-[0.7rem] text-muted-foreground">
            Only checked categories are traced back to the OSL. Scoping runs in code; no model call.
          </span>
        </CardHeader>
        {!categories ? (
          <Skeleton className="m-4 h-24" />
        ) : (
          <Table>
            <thead>
              <TR className="hover:bg-transparent">
                <TH>Category</TH>
                <TH>Config key families</TH>
                <TH>Checked</TH>
              </TR>
            </thead>
            <tbody>
              {categories.map((category) => (
                <TR key={category.name}>
                  <TD className="font-semibold">{category.name}</TD>
                  <TD className="mono text-xs">{category.kinds.join(", ") || "—"}</TD>
                  <TD>
                    <Button
                      size="xs"
                      variant={category.checked ? "success" : "outline"}
                      disabled={busy}
                      onClick={() => void toggleCategory(category)}
                    >
                      {category.checked ? "Checked" : "Ignored"}
                    </Button>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
        <CardContent className="border-t pt-3">
          <p className="text-xs text-muted-foreground">
            An extra element in a checked category becomes a medium-severity finding. Everything
            else is ignored, because the OSL does not describe every detail of the extract.
          </p>
        </CardContent>
      </Card>
    </>
  );
}

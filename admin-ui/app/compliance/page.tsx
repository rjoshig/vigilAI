"use client";

/**
 * Compliance rules and reverse-pass scope.
 *
 * Compliance rules work the other way round from OSL requirements: each one must be
 * present in the config even if the OSL never mentions it. The reverse pass is scoped,
 * not exhaustive, because the OSL does not describe every detail of the extract
 * process (`docs/design.md` "Processing pipeline", step 6).
 */

import { Trash2 } from "lucide-react";
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
import type { Category, ComplianceRule } from "@/lib/types";

export default function CompliancePage() {
  const [rules, setRules] = React.useState<ComplianceRule[] | null>(null);
  const [categories, setCategories] = React.useState<Category[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [draft, setDraft] = React.useState({ name: "", json_path_contains: "", reasoning: "" });

  const load = React.useCallback(async () => {
    try {
      const [nextRules, nextCategories] = await Promise.all([
        api.listComplianceRules(),
        api.listCategories(),
      ]);
      setRules(nextRules);
      setCategories(nextCategories);
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
        expected_value: true,
        scope: "all",
        reasoning: draft.reasoning,
        is_active: true,
      });
      setDraft({ name: "", json_path_contains: "", reasoning: "" });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the rule.");
    } finally {
      setBusy(false);
    }
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
          <Table>
            <thead>
              <TR className="hover:bg-transparent">
                <TH>Name</TH>
                <TH>Config path must contain</TH>
                <TH>Scope</TH>
                <TH>Reasoning</TH>
                <TH />
              </TR>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <TR key={rule.id}>
                  <TD className="font-semibold">{rule.name}</TD>
                  <TD className="mono text-xs">{rule.json_path_contains}</TD>
                  <TD className="text-xs">{rule.scope}</TD>
                  <TD className="text-xs text-muted-foreground">{rule.reasoning || "—"}</TD>
                  <TD className="text-right">
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={busy}
                      aria-label={`Delete ${rule.name}`}
                      onClick={async () => {
                        await api.deleteComplianceRule(rule.id);
                        await load();
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
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
            <Label htmlFor="cr-path">Config path contains</Label>
            <Input
              id="cr-path"
              className="mono"
              placeholder="suppressions.ofac"
              value={draft.json_path_contains}
              onChange={(event) => setDraft({ ...draft, json_path_contains: event.target.value })}
            />
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
          <div className="flex items-end">
            <Button
              disabled={!draft.name.trim() || !draft.json_path_contains.trim() || busy}
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

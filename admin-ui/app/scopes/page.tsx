"use client";

/**
 * Delivery programmes: AM, AS, Archives, and the catch-all (ADR-020).
 *
 * A run names one of these, and the standing instructions written here reach the model
 * as background. They are the compliance regime the OSL usually does not restate, so
 * this is the one place to say it rather than in every OSL.
 */

import { Plus, Trash2 } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  PageHeader,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Scope } from "@/lib/types";

const NEW_SCOPE = {
  code: "",
  label: "",
  description: "",
  standing_instructions: "",
  is_active: true,
  sort_order: 100,
};

export default function ScopesPage() {
  const [scopes, setScopes] = React.useState<Scope[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [fresh, setFresh] = React.useState({ ...NEW_SCOPE });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setScopes(await api.listScopes());
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

  return (
    <>
      <PageHeader
        title="Delivery programmes"
        description="Most customers fall into Account Monitoring, Account Solicitation, or Archives; everything else is clubbed together. What you write here reaches the model as background for every run in that programme."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="mb-4 flex justify-end">
        <Button size="xs" variant="outline" onClick={() => setAdding(!adding)}>
          <Plus className="h-3.5 w-3.5" /> Add a programme
        </Button>
      </div>

      {adding ? (
        <Card className="mb-4">
          <CardHeader className="border-b">
            <CardTitle>New programme</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 pt-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="sc-code">Code</Label>
              <Input
                id="sc-code"
                className="mono"
                placeholder="PRESCREEN"
                value={fresh.code}
                onChange={(event) => setFresh({ ...fresh, code: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="sc-label">Label</Label>
              <Input
                id="sc-label"
                placeholder="Prescreen"
                value={fresh.label}
                onChange={(event) => setFresh({ ...fresh, label: event.target.value })}
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                disabled={!fresh.code.trim() || !fresh.label.trim() || busy}
                onClick={() =>
                  void act("add the programme", async () => {
                    await api.saveScope(fresh);
                    setFresh({ ...NEW_SCOPE });
                    setAdding(false);
                  })
                }
              >
                Add programme
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!scopes ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="grid gap-4">
          {scopes.map((scope) => (
            <ScopeCard
              key={scope.code}
              scope={scope}
              busy={busy}
              onSave={(changes) =>
                void act("save the programme", () => api.saveScope({ ...scope, ...changes }))
              }
              onDelete={() => void act("delete the programme", () => api.deleteScope(scope.code))}
            />
          ))}
        </div>
      )}
    </>
  );
}

/** One programme, with its standing instructions. */
function ScopeCard({
  scope,
  busy,
  onSave,
  onDelete,
}: {
  scope: Scope;
  busy: boolean;
  onSave: (changes: Partial<Scope>) => void;
  onDelete: () => void;
}) {
  const [label, setLabel] = React.useState(scope.label);
  const [description, setDescription] = React.useState(scope.description);
  const [instructions, setInstructions] = React.useState(scope.standing_instructions);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between border-b">
        <div className="flex items-center gap-2">
          <CardTitle>
            <span className="mono">{scope.code}</span> · {scope.label}
          </CardTitle>
          {scope.is_active ? null : <Badge tone="muted">off</Badge>}
          {scope.runs_using > 0 ? <Badge tone="muted">{scope.runs_using} run(s)</Badge> : null}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs">
            <input
              type="checkbox"
              checked={scope.is_active}
              disabled={busy}
              aria-label={`Offer ${scope.label} on the new-run form`}
              onChange={(event) => onSave({ is_active: event.target.checked })}
            />
            Offered to users
          </label>
          <Button
            variant="ghost"
            size="xs"
            disabled={busy || scope.runs_using > 0}
            aria-label={`Delete ${scope.label}`}
            onClick={onDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 pt-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor={`sl-${scope.code}`}>Label</Label>
            <Input
              id={`sl-${scope.code}`}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`sd-${scope.code}`}>What the programme is</Label>
            <Input
              id={`sd-${scope.code}`}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`si-${scope.code}`}>Standing instructions</Label>
          <Textarea
            id={`si-${scope.code}`}
            rows={3}
            placeholder="Compliance expectations true of every run in this programme. Leave empty and nothing is added to the prompts."
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
          />
          <span className="text-[0.7rem] text-muted-foreground">
            Background for reading the OSL, never a substitute for what the OSL says.
          </span>
        </div>
        <div>
          <Button
            disabled={busy}
            onClick={() => onSave({ label, description, standing_instructions: instructions })}
          >
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

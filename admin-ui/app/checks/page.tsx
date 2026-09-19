"use client";

/**
 * Checks: describe in plain English, correct the proposal, test it, activate.
 *
 * Drafting is the only LLM call in the admin flow and it happens once per check. After
 * that the check runs as code on every request at no token cost
 * (`docs/design.md` "Configurable checks").
 */

import { AlertTriangle, FlaskConical, Plus, Sparkles, Zap } from "lucide-react";
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
import { ScopePicker, scopeLabel } from "@/components/scope-picker";
import { api, ApiError } from "@/lib/api";
import type { Check, CheckIn, DraftResponse, Scope, Severity, TestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY_TONE: Record<Severity, "destructive" | "warn" | "info" | "muted"> = {
  high: "destructive",
  medium: "warn",
  low: "info",
  review: "muted",
};

const EMPTY: CheckIn = {
  name: "",
  kind: "expression",
  expression: "",
  instruction: "",
  reasoning: "",
  severity: "medium",
  scope: "all",
  is_active: true,
};

export default function ChecksPage() {
  const [checks, setChecks] = React.useState<Check[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [authoring, setAuthoring] = React.useState(false);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [nextChecks, nextProgrammes] = await Promise.all([api.listChecks(), api.listScopes()]);
      setChecks(nextChecks);
      setProgrammes(nextProgrammes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function toggle(check: Check) {
    try {
      await api.setCheckActive(check.id, !check.is_active);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not change the check.");
    }
  }

  return (
    <>
      <PageHeader
        title="Checks"
        description="Cross-report checks defined as data. The model helps write a check once; code runs it on every request at no token cost. Versioned, scoped, and switchable. Evaluated by code on every run; nothing here is sent to the model."
        action={
          <Button onClick={() => setAuthoring(true)}>
            <Plus className="h-4 w-4" /> New check
          </Button>
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      {!checks ? <Skeleton className="h-64" /> : null}

      {checks ? (
        <Card className="p-0">
          {checks.length === 0 ? (
            <EmptyState
              title="No checks yet"
              hint="Describe one in plain English and the model will propose the named values and the expression."
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH>Name</TH>
                  <TH>Ver</TH>
                  <TH>Kind</TH>
                  <TH className="min-w-[16rem]">Expression / instruction</TH>
                  <TH>Severity</TH>
                  <TH>Scope</TH>
                  <TH>Active</TH>
                </TR>
              </thead>
              <tbody>
                {checks.map((check) => (
                  <TR key={check.id} className={cn(!check.is_active && "opacity-60")}>
                    <TD>
                      <div className="font-semibold">{check.name}</div>
                      {check.reasoning ? (
                        <div className="text-xs text-muted-foreground">{check.reasoning}</div>
                      ) : null}
                    </TD>
                    <TD className="tabular-nums">v{check.version}</TD>
                    <TD>
                      <Badge tone={check.kind === "judgment" ? "warn" : "muted"}>
                        {check.kind}
                        {check.kind === "judgment" ? " · use sparingly" : ""}
                      </Badge>
                    </TD>
                    <TD className="mono text-xs">{check.expression || check.instruction}</TD>
                    <TD>
                      <Badge tone={SEVERITY_TONE[check.severity]}>{check.severity}</Badge>
                    </TD>
                    <TD className="text-xs">{scopeLabel(check.scope, programmes)}</TD>
                    <TD>
                      <Button
                        size="xs"
                        variant={check.is_active ? "success" : "outline"}
                        onClick={() => void toggle(check)}
                      >
                        {check.is_active ? "On" : "Off"}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : null}

      {authoring ? (
        <AuthorDialog
          programmes={programmes}
          onClose={() => setAuthoring(false)}
          onSaved={() => {
            setAuthoring(false);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

function AuthorDialog({
  onClose,
  onSaved,
  programmes,
}: {
  onClose: () => void;
  onSaved: () => void;
  programmes: Scope[] | null;
}) {
  const [description, setDescription] = React.useState("");
  const [draft, setDraft] = React.useState<DraftResponse | null>(null);
  const [check, setCheck] = React.useState<CheckIn>({ ...EMPTY });
  const [result, setResult] = React.useState<TestResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function propose() {
    setBusy(true);
    setError(null);
    try {
      const proposal = await api.draftCheck(description);
      setDraft(proposal);
      setCheck({
        ...EMPTY,
        expression: proposal.expression,
        reasoning: proposal.reasoning,
        severity: proposal.severity,
      });
      // Named values the proposal introduced have to exist before a test can resolve
      // them, so they are saved as part of accepting the proposal.
      for (const value of proposal.named_values) {
        await api.saveNamedValue(value);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "The model could not draft this.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    try {
      setResult(await api.testExpression(check.expression));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not test the expression.");
    } finally {
      setBusy(false);
    }
  }

  async function activate() {
    setBusy(true);
    try {
      await api.saveCheck({ ...check, is_active: true });
      onSaved();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the check.");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="author-title"
    >
      <Card className="max-h-[90vh] w-full max-w-4xl overflow-auto">
        <CardHeader className="border-b">
          <CardTitle id="author-title">New check</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </CardHeader>

        <CardContent className="grid gap-5 pt-4 lg:grid-cols-2">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="description">1 · Describe the rule in plain English</Label>
              <Textarea
                id="description"
                className="min-h-[7rem]"
                placeholder="Compare the billing count in the billing report with the delivered count in the number flow report. Billing must not be more than delivered."
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
            <Button
              variant="secondary"
              disabled={description.trim().length < 10 || busy}
              onClick={() => void propose()}
            >
              <Sparkles className="h-4 w-4" /> Propose named values and expression
            </Button>
            <p className="text-[0.7rem] text-muted-foreground">
              One model call, once. After activation the check runs as code on every run.
            </p>
            {error ? <ErrorState message={error} /> : null}
          </div>

          {draft ? (
            <div className="flex flex-col gap-3">
              <div className="text-xs font-medium">2 · Correct the proposal</div>

              {draft.warnings.length > 0 ? (
                <div className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 p-2.5 text-xs">
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-warn" />
                  <ul className="list-disc pl-4">
                    {draft.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {draft.named_values.length > 0 ? (
                <div className="rounded-md border p-2.5 text-xs">
                  <div className="mb-1 font-medium">Named values saved</div>
                  <ul className="mono space-y-0.5 text-[0.7rem] text-muted-foreground">
                    {draft.named_values.map((value) => (
                      <li key={value.name}>
                        {value.name} — {value.report_type} · {value.sheet}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="flex flex-col gap-1">
                <Label htmlFor="check-name">Name</Label>
                <Input
                  id="check-name"
                  className="mono"
                  placeholder="billing_not_above_delivered"
                  value={check.name}
                  onChange={(event) => setCheck({ ...check, name: event.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1">
                <Label htmlFor="check-expression">Expression</Label>
                <Input
                  id="check-expression"
                  className="mono"
                  value={check.expression}
                  onChange={(event) => setCheck({ ...check, expression: event.target.value })}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="check-severity">Severity</Label>
                  <Select
                    id="check-severity"
                    value={check.severity}
                    onChange={(event) =>
                      setCheck({ ...check, severity: event.target.value as Severity })
                    }
                  >
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </Select>
                </div>
              </div>

              <ScopePicker
                idPrefix="check"
                value={check.scope}
                programmes={programmes}
                onChange={(scope) => setCheck({ ...check, scope })}
              />

              <div className="flex flex-col gap-1">
                <Label htmlFor="check-reasoning">Reasoning shown to users</Label>
                <Input
                  id="check-reasoning"
                  value={check.reasoning}
                  onChange={(event) => setCheck({ ...check, reasoning: event.target.value })}
                />
              </div>

              <Button
                variant="outline"
                disabled={!check.expression.trim() || busy}
                onClick={() => void test()}
              >
                <FlaskConical className="h-4 w-4" /> 3 · Test against the samples
              </Button>

              {result ? (
                <div
                  className={cn(
                    "rounded-md border p-2.5 text-xs",
                    result.passed === true && "border-success/40 bg-success/10",
                    result.passed === false && "border-destructive/40 bg-destructive/10",
                    result.passed === null && "border-warn/40 bg-warn/10"
                  )}
                >
                  <div className="font-semibold">
                    {result.passed === true
                      ? "Passes on the samples"
                      : result.passed === false
                        ? "Fails on the samples"
                        : "Could not be evaluated"}
                  </div>
                  <div className="mt-0.5 text-muted-foreground">{result.detail}</div>
                </div>
              ) : null}

              <Button
                disabled={!check.name.trim() || !check.expression.trim() || busy}
                onClick={() => void activate()}
              >
                <Zap className="h-4 w-4" /> 4 · Activate
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

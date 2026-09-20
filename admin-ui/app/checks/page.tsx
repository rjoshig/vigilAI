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
  Select,
  Skeleton,
  TD,
  TH,
  TR,
  Table,
  Textarea,
} from "@/components/ui/primitives";
import { BulkBar } from "@/components/bulk-bar";
import { EVERYWHERE, ScopePicker, scopeLabel } from "@/components/scope-picker";
import { api, ApiError } from "@/lib/api";
import type {
  Check,
  CheckIn,
  CheckKind,
  DraftResponse,
  NamedValue,
  Scope,
  Severity,
  TestResult,
} from "@/lib/types";
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
  value_names: [],
  reasoning: "",
  severity: "medium",
  scope: EVERYWHERE,
  is_active: true,
};

export default function ChecksPage() {
  const [checks, setChecks] = React.useState<Check[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [authoring, setAuthoring] = React.useState<false | "new" | Check>(false);
  const [selected, setSelected] = React.useState<number[]>([]);
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
        explain={
          <Explain label="What is this for?">
            A check is a rule <b>code evaluates</b> against a report: a named value compared with a
            threshold, a count that must reconcile. It produces a finding and always gives the same
            answer on the same inputs.
            <br />
            <br />
            Not here: something that must hold across a whole programme is a <b>programme rule</b>;
            something that must be <i>present in the configuration</i> is a <b>compliance rule</b>;
            something the model should know rather than test is an artifact type&rsquo;s{" "}
            <b>AI context</b>.
          </Explain>
        }
        title="Checks"
        description="Cross-report checks defined as data. The model helps write a check once; code runs it on every request at no token cost. Versioned, scoped, and switchable. Evaluated by code on every run; nothing here is sent to the model."
        action={
          <Button onClick={() => setAuthoring("new")}>
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

      <p className="mb-3 text-xs text-muted-foreground">
        A check is arithmetic over named values, evaluated by code. To tell the model what a report
        cell <i>means</i> and where it answers to, use the report type&apos;s guide on Artifact
        types; a concrete guide entry becomes a check here on its own.
      </p>

      {checks ? (
        <Card className="p-0">
          <div className="px-4 pt-3">
            <BulkBar
              count={selected.length}
              actions={[
                { word: "delete", label: "Delete selected (restorable)", destructive: true },
              ]}
              onClear={() => setSelected([])}
              onAct={async (confirm) => {
                await api.bulkDelete("checks", selected, confirm);
                setSelected([]);
                await load();
              }}
            />
          </div>
          {checks.length === 0 ? (
            <EmptyState
              title="No checks yet"
              hint="Describe one in plain English and the model will propose the named values and the expression."
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH className="w-8" />
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
                      <input
                        type="checkbox"
                        aria-label={`Select ${check.name}`}
                        checked={selected.includes(check.id)}
                        onChange={() =>
                          setSelected((current) =>
                            current.includes(check.id)
                              ? current.filter((one) => one !== check.id)
                              : [...current, check.id]
                          )
                        }
                      />
                    </TD>
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
                      </Button>{" "}
                      <Button size="xs" variant="ghost" onClick={() => setAuthoring(check)}>
                        Edit
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
          initial={authoring === "new" ? null : authoring}
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
  initial,
}: {
  onClose: () => void;
  onSaved: () => void;
  programmes: Scope[] | null;
  /** An existing check to edit; saving it writes a new version under the same name. */
  initial: Check | null;
}) {
  const [description, setDescription] = React.useState("");
  const [draft, setDraft] = React.useState<DraftResponse | null>(null);
  // Every named value the tool knows, for a judgment check to pick from (Phase 6.13c).
  const [namedValues, setNamedValues] = React.useState<NamedValue[]>([]);
  React.useEffect(() => {
    api
      .listNamedValues()
      .then(setNamedValues)
      .catch(() => {
        // Without the list a judgment check can still be typed; the names are checked
        // when the run resolves them.
      });
  }, []);
  const [check, setCheck] = React.useState<CheckIn>(
    initial
      ? {
          name: initial.name,
          kind: initial.kind,
          expression: initial.expression,
          instruction: initial.instruction,
          value_names: [...initial.value_names],
          reasoning: initial.reasoning,
          severity: initial.severity,
          scope: initial.scope,
          is_active: initial.is_active,
        }
      : { ...EMPTY }
  );
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
                <Label htmlFor="check-kind">How is it decided?</Label>
                <Select
                  id="check-kind"
                  value={check.kind}
                  onChange={(event) =>
                    setCheck({ ...check, kind: event.target.value as CheckKind })
                  }
                >
                  <option value="expression">A formula — code evaluates it, no model call</option>
                  <option value="judgment">
                    A judgment — the model reads named values against an instruction
                  </option>
                </Select>
                {check.kind === "judgment" ? (
                  <p className="text-[0.7rem] text-warn">
                    Use sparingly: a judgment check costs one model call on every run in its scope.
                    The model sees only the named values you list below, never a report, and answers
                    pass, fail or review; code sets the severity.
                  </p>
                ) : null}
              </div>

              {check.kind === "expression" ? (
                <div className="flex flex-col gap-1">
                  <Label htmlFor="check-expression">Expression</Label>
                  <Input
                    id="check-expression"
                    className="mono"
                    value={check.expression}
                    onChange={(event) => setCheck({ ...check, expression: event.target.value })}
                  />
                </div>
              ) : (
                <>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="check-instruction">What should the model judge?</Label>
                    <Textarea
                      id="check-instruction"
                      className="min-h-[4rem]"
                      placeholder="The state mix should be plausible for a campaign limited to two states."
                      value={check.instruction}
                      onChange={(event) => setCheck({ ...check, instruction: event.target.value })}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="check-values">Which named values may the model see?</Label>
                    <select
                      id="check-values"
                      multiple
                      className="mono min-h-[6rem] rounded-md border bg-background px-2 py-1 text-xs"
                      value={check.value_names}
                      onChange={(event) =>
                        setCheck({
                          ...check,
                          value_names: Array.from(event.target.selectedOptions, (o) => o.value),
                        })
                      }
                    >
                      {namedValues.map((value) => (
                        <option key={value.name} value={value.name}>
                          {value.name} — {value.report_type}
                          {value.sheet ? ` · ${value.sheet}` : ""}
                        </option>
                      ))}
                    </select>
                    <span className="text-[0.7rem] text-muted-foreground">
                      Only these reach the model. Define a named value under Artifact types first if
                      the one you need is not listed.
                    </span>
                  </div>
                </>
              )}

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

              {check.kind === "expression" ? (
                <Button
                  variant="outline"
                  disabled={!check.expression.trim() || busy}
                  onClick={() => void test()}
                >
                  <FlaskConical className="h-4 w-4" /> 3 · Test against the samples
                </Button>
              ) : null}

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
                disabled={
                  !check.name.trim() ||
                  busy ||
                  (check.kind === "expression"
                    ? !check.expression.trim()
                    : !check.instruction.trim() || check.value_names.length === 0)
                }
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

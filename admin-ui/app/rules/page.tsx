"use client";

/**
 * Every rule the tool holds, in one place (ADR-021). This is the screen someone opens
 * when a finding surprises them, so search covers the plain-language reasoning as well
 * as the name, and the origin column says whether a rule was shipped, written here, or
 * learned from an observation.
 */

import { EyeOff, History, Scale, Search } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
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
import Link from "next/link";

import { BulkBar } from "@/components/bulk-bar";
import { scopeLabel } from "@/components/scope-picker";
import { api, ApiError } from "@/lib/api";
import type {
  Rule,
  RuleActionWord,
  RuleStateChange,
  RuleStateFilter,
  ShadowFinding,
} from "@/lib/types";

const STATES: RuleStateFilter[] = ["active", "shadow", "disabled", "deleted", "draft", "all"];

const STATE_TONES: Record<string, "success" | "info" | "muted" | "destructive" | "warn"> = {
  active: "success",
  shadow: "info",
  disabled: "muted",
  deleted: "destructive",
  draft: "warn",
};

const ORIGIN_LABELS: Record<string, string> = {
  shipped: "shipped",
  admin: "written here",
  learned: "learned",
  guide: "from a validation guide",
};

/**
 * The kinds that arrive as one token but read better as words. A kind not listed
 * here is shown as stored, so a new kind is still recognisable before this map
 * learns it.
 */
const KIND_LABELS: Record<string, string> = {
  programme_rule: "Programme rule",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

function when(value: string | null): string {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** Where a rule's wording is edited, by kind; null when it has no owning screen. */
function editHref(ruleKind: string, id: number): string | null {
  if (ruleKind === "check") return `/checks?focus=${id}`;
  if (ruleKind === "compliance_rule") return `/compliance?focus=${id}`;
  if (ruleKind === "programme_rule") return `/scopes?focus=${id}`;
  return null;
}

/** Which state changes make sense from where the rule is now. */
function actionsFor(state: string): RuleActionWord[] {
  if (state === "deleted") return ["restore"];
  if (state === "shadow") return ["activate", "disable", "delete"];
  if (state === "disabled") return ["enable", "delete"];
  if (state === "draft") return ["activate", "delete"];
  return ["disable", "delete"];
}

/**
 * The confirmation. The administrator types the action word rather than clicking a
 * second time, because a rule change reaches every future run — and because the API
 * enforces the same thing with a 400, so a second click would simply fail.
 */
function ConfirmAction({
  action,
  busy,
  onConfirm,
  onCancel,
}: {
  action: RuleActionWord;
  busy: boolean;
  onConfirm: (confirm: string, note: string) => void;
  onCancel: () => void;
}) {
  const [typed, setTyped] = React.useState("");
  const [note, setNote] = React.useState("");

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-muted/40 p-2">
      <Label htmlFor={`confirm-${action}`}>
        Type <span className="mono font-semibold">{action}</span> to confirm
      </Label>
      <Input
        id={`confirm-${action}`}
        className="mono h-7 w-32 text-xs"
        autoComplete="off"
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
      <Input
        className="h-7 w-48 text-xs"
        aria-label="Note"
        placeholder="note (optional)"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <Button
        size="xs"
        variant={action === "delete" ? "destructive" : "default"}
        disabled={busy || typed.trim() !== action}
        onClick={() => onConfirm(typed.trim(), note.trim())}
      >
        {action}
      </Button>
      <Button size="xs" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

export default function RulesPage() {
  const [rules, setRules] = React.useState<Rule[] | null>(null);
  const [state, setState] = React.useState<RuleStateFilter>("active");
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [confirming, setConfirming] = React.useState<string | null>(null);
  const [history, setHistory] = React.useState<Record<string, RuleStateChange[]>>({});
  const [openHistory, setOpenHistory] = React.useState<string | null>(null);
  const [shadow, setShadow] = React.useState<Record<string, ShadowFinding[]>>({});
  const [openShadow, setOpenShadow] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<Rule[]>([]);

  const load = React.useCallback(async () => {
    try {
      // Sorting is the server's, so the rows go on screen in the order they arrive.
      setRules(await api.listRules(state, query));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [state, query]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      setConfirming(null);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : `Could not ${what} the rule.`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory(rule: Rule) {
    const key = `${rule.rule_kind}-${rule.id}`;
    if (openHistory === key) {
      setOpenHistory(null);
      return;
    }
    setOpenHistory(key);
    if (history[key]) return;
    try {
      const loaded = await api.ruleHistory(rule.rule_kind, rule.id);
      setHistory((current) => ({ ...current, [key]: loaded }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not read the rule's history.");
    }
  }

  async function toggleShadow(rule: Rule) {
    const key = `${rule.rule_kind}-${rule.id}`;
    if (openShadow === key) {
      setOpenShadow(null);
      return;
    }
    setOpenShadow(key);
    try {
      const loaded = await api.shadowFindings(rule.rule_kind, rule.id);
      setShadow((current) => ({ ...current, [key]: loaded }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not read the shadow findings.");
    }
  }

  async function dismiss(rule: Rule, finding: ShadowFinding) {
    const key = `${rule.rule_kind}-${rule.id}`;
    await act("dismiss the shadow finding of", async () => {
      await api.dismissShadowFinding(finding.id, "not a real problem, judged in shadow");
      const loaded = await api.shadowFindings(rule.rule_kind, rule.id);
      setShadow((current) => ({ ...current, [key]: loaded }));
    });
  }

  return (
    <>
      <PageHeader
        title="Rules"
        description="Every rule the tool runs, whatever its origin. A shadow rule runs and is counted but no reviewer sees its findings; deleting is reversible for as long as the restore window lasts."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="rule-search">Search name, summary, and reasoning</Label>
          <div className="flex gap-1.5">
            <Input
              id="rule-search"
              className="w-80"
              placeholder="why did this fire?"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") setQuery(search.trim());
              }}
            />
            <Button variant="outline" size="sm" onClick={() => setQuery(search.trim())}>
              <Search className="h-3.5 w-3.5" /> Search
            </Button>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="rule-state">State</Label>
          <Select
            id="rule-state"
            value={state}
            onChange={(event) => setState(event.target.value as RuleStateFilter)}
          >
            {STATES.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {!rules ? (
        <Skeleton className="h-64" />
      ) : rules.length === 0 ? (
        <EmptyState
          title="No rules match"
          hint="Widen the state filter, or clear the search box."
        />
      ) : (
        <>
          <BulkBar
            count={selected.length}
            busy={busy}
            actions={[
              { word: "disable", label: "Disable selected" },
              { word: "enable", label: "Enable selected" },
              { word: "activate", label: "Activate selected (shadow → active)" },
              { word: "delete", label: "Delete selected (restorable)", destructive: true },
            ]}
            onClear={() => setSelected([])}
            onAct={(confirm) =>
              act(confirm, async () => {
                const result = await api.actOnRules(
                  selected.map((one) => ({ rule_kind: one.rule_kind, id: one.id })),
                  confirm as RuleActionWord,
                  confirm
                );
                setSelected([]);
                if (result.failed.length > 0) {
                  throw new ApiError(
                    409,
                    `${result.changed} changed; could not: ${result.failed.join("; ")}`
                  );
                }
              })
            }
          />
          <Card>
            <CardContent className="p-0">
              <Table>
                <thead>
                  <TR className="hover:bg-transparent">
                    <TH className="w-8" />
                    <TH>Rule</TH>
                    <TH>Origin</TH>
                    <TH>State</TH>
                    <TH>Scope</TH>
                    <TH>Severity</TH>
                    <TH>Fired</TH>
                    <TH>Dismissed</TH>
                    <TH>Last fired</TH>
                    <TH className="text-right">Actions</TH>
                  </TR>
                </thead>
                <tbody>
                  {rules.map((rule) => {
                    const key = `${rule.rule_kind}-${rule.id}`;
                    return (
                      <React.Fragment key={key}>
                        <TR>
                          <TD>
                            <input
                              type="checkbox"
                              aria-label={`Select ${rule.name}`}
                              checked={selected.some(
                                (one) => one.rule_kind === rule.rule_kind && one.id === rule.id
                              )}
                              onChange={() =>
                                setSelected((current) =>
                                  current.some(
                                    (one) => one.rule_kind === rule.rule_kind && one.id === rule.id
                                  )
                                    ? current.filter(
                                        (one) =>
                                          !(one.rule_kind === rule.rule_kind && one.id === rule.id)
                                      )
                                    : [...current, rule]
                                )
                              }
                            />
                          </TD>
                          <TD>
                            <div className="text-sm font-medium">{rule.name}</div>
                            <div className="mono text-[0.7rem] text-muted-foreground">
                              {kindLabel(rule.rule_kind)} #{rule.id}
                            </div>
                            {rule.summary ? (
                              <div className="max-w-md text-xs text-muted-foreground">
                                {rule.summary}
                              </div>
                            ) : null}
                            {rule.source_observation_ids.length > 0 ? (
                              <div className="text-[0.7rem] text-muted-foreground">
                                from observation {rule.source_observation_ids.join(", ")}
                              </div>
                            ) : null}
                            {rule.state === "deleted" && rule.restorable_until ? (
                              <div className="text-[0.7rem] text-destructive">
                                restorable until {when(rule.restorable_until)}
                              </div>
                            ) : null}
                          </TD>
                          <TD>
                            <Badge tone="outline">
                              {ORIGIN_LABELS[rule.origin] ?? rule.origin}
                            </Badge>
                          </TD>
                          <TD>
                            <Badge tone={STATE_TONES[rule.state] ?? "muted"}>{rule.state}</Badge>
                          </TD>
                          <TD className="text-xs">{scopeLabel(rule.scope, null)}</TD>
                          <TD className="text-xs">{rule.severity}</TD>
                          <TD className="tabular-nums">{rule.fired}</TD>
                          <TD className="tabular-nums">
                            {rule.dismissed} ({Math.round(rule.dismissal_rate * 100)}%)
                          </TD>
                          <TD className="text-xs text-muted-foreground">
                            {when(rule.last_fired_at)}
                          </TD>
                          <TD className="text-right">
                            <div className="flex flex-wrap justify-end gap-1">
                              {actionsFor(rule.state).map((action) => (
                                <Button
                                  key={action}
                                  variant={action === "delete" ? "ghost" : "outline"}
                                  size="xs"
                                  disabled={busy}
                                  onClick={() => setConfirming(`${key}-${action}`)}
                                >
                                  {action}
                                </Button>
                              ))}
                              {editHref(rule.rule_kind, rule.id) ? (
                                <Link
                                  href={editHref(rule.rule_kind, rule.id) ?? "#"}
                                  className="inline-flex h-6 items-center rounded px-2 text-xs hover:bg-accent"
                                >
                                  Edit
                                </Link>
                              ) : null}
                              <Button
                                variant="ghost"
                                size="xs"
                                aria-label={`History of ${rule.name}`}
                                onClick={() => void toggleHistory(rule)}
                              >
                                <History className="h-3.5 w-3.5" /> History
                              </Button>
                              {rule.state === "shadow" || rule.fired > 0 ? (
                                <Button
                                  variant="ghost"
                                  size="xs"
                                  aria-label={`Shadow findings of ${rule.name}`}
                                  title="What this rule found while nobody could see it"
                                  onClick={() => void toggleShadow(rule)}
                                >
                                  <EyeOff className="h-3.5 w-3.5" /> Shadow findings
                                </Button>
                              ) : null}
                            </div>
                          </TD>
                        </TR>

                        {openShadow === key ? (
                          <TR className="hover:bg-transparent">
                            <TD colSpan={10} className="bg-muted/30">
                              {!shadow[key] ? (
                                <Skeleton className="h-10" />
                              ) : shadow[key].length === 0 ? (
                                <p className="text-xs text-muted-foreground">
                                  This rule has produced no shadow finding yet. Precision is unknown
                                  until it meets real runs.
                                </p>
                              ) : (
                                <div className="text-xs">
                                  <p className="mb-1 text-muted-foreground">
                                    Reviewers never see these. Say when one is not a real problem:
                                    that is what a shadow rule&apos;s dismissal rate is made of, and
                                    what decides whether to activate it.
                                  </p>
                                  <ul className="space-y-1">
                                    {shadow[key].map((finding) => (
                                      <li
                                        key={finding.id}
                                        className="flex flex-wrap items-center gap-2"
                                        data-testid="shadow-finding"
                                      >
                                        <span className="mono text-muted-foreground">
                                          VR-{String(finding.run_id).padStart(4, "0")} ·{" "}
                                          {finding.finding_id}
                                        </span>
                                        <span className="font-medium">{finding.title}</span>
                                        {finding.review_status === "false_positive" ? (
                                          <Badge tone="muted">dismissed</Badge>
                                        ) : (
                                          <Button
                                            size="xs"
                                            variant="outline"
                                            disabled={busy}
                                            onClick={() => void dismiss(rule, finding)}
                                          >
                                            Not a real problem
                                          </Button>
                                        )}
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                            </TD>
                          </TR>
                        ) : null}

                        {actionsFor(rule.state).map((action) =>
                          confirming === `${key}-${action}` ? (
                            <TR key={`${key}-${action}-confirm`} className="hover:bg-transparent">
                              <TD colSpan={10}>
                                <ConfirmAction
                                  action={action}
                                  busy={busy}
                                  onCancel={() => setConfirming(null)}
                                  onConfirm={(confirm, note) =>
                                    void act(action, () =>
                                      api.actOnRule(rule.rule_kind, rule.id, action, confirm, note)
                                    )
                                  }
                                />
                              </TD>
                            </TR>
                          ) : null
                        )}

                        {openHistory === key ? (
                          <TR className="hover:bg-transparent">
                            <TD colSpan={10} className="bg-muted/30">
                              {!history[key] ? (
                                <Skeleton className="h-10" />
                              ) : history[key].length === 0 ? (
                                <p className="text-xs text-muted-foreground">
                                  This rule has not changed state since it was created.
                                </p>
                              ) : (
                                <ul className="text-xs">
                                  {history[key].map((change) => (
                                    <li key={change.id} className="py-0.5">
                                      <span className="mono">
                                        {change.from_state || "—"} → {change.to_state}
                                      </span>{" "}
                                      · {change.actor || "—"} · {when(change.at)}
                                      {change.note ? ` · ${change.note}` : ""}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </TD>
                          </TR>
                        ) : null}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}

      <p className="mt-3 text-xs text-muted-foreground">
        <Scale className="mr-1 inline h-3.5 w-3.5" />
        Disabling or deleting a rule never edits a finding that already exists; past runs stay
        reproducible.
      </p>
    </>
  );
}

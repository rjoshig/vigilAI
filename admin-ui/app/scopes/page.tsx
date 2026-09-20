"use client";

/**
 * Delivery programmes: AM, AS, Archives, and the catch-all (ADR-020).
 *
 * A run names one of these, and the standing instructions written here reach the model
 * as background. They are the compliance regime the OSL usually does not restate, so
 * this is the one place to say it rather than in every OSL.
 *
 * Each programme also carries keywords, which code greps the inputs for to confirm a
 * run really is that programme, and programme rules, which the model reads each
 * delivery against. Rule state changes go through the rules action endpoint, so they
 * carry the same typed confirmation and history as every other rule.
 */

import { Pencil, Plus } from "lucide-react";
import * as React from "react";

import { Explain, FieldEffect } from "@/components/explain";
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
  Select,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { VersionsPanel } from "@/components/versions-panel";
import { DeleteButton } from "@/components/confirm-delete";
import { api, ApiError } from "@/lib/api";
import { versionLabel } from "@/lib/versions";
import type {
  ProgrammeRule,
  ProgrammeRuleIn,
  RuleActionWord,
  Scope,
  Strictness,
} from "@/lib/types";
import { STRICTNESS_LEVELS } from "@/lib/types";

const NEW_SCOPE: Omit<Scope, "id" | "runs_using"> = {
  code: "",
  label: "",
  description: "",
  standing_instructions: "",
  keywords: [],
  is_active: true,
  sort_order: 100,
  // Off by default: programmes differ in what a waved-through compliance finding
  // costs, and a rule that is right for one is wrong for most (ADR-036).
  second_approver: false,
  version: 0,
};

const DEFAULT_STRICTNESS: Strictness = "should";

const STRICTNESS_TONES: Record<Strictness, "destructive" | "warn" | "info"> = {
  must: "destructive",
  should: "warn",
  advisory: "info",
};

const STATE_TONES: Record<string, "success" | "info" | "muted" | "destructive" | "warn"> = {
  active: "success",
  shadow: "info",
  disabled: "muted",
  deleted: "destructive",
  draft: "warn",
};

/** A comma-separated field becomes a list; blanks and repeats are dropped. */
function parseKeywords(text: string): string[] {
  const seen = new Set<string>();
  return text
    .split(",")
    .map((word) => word.trim())
    .filter((word) => {
      if (!word || seen.has(word.toLowerCase())) return false;
      seen.add(word.toLowerCase());
      return true;
    });
}

/**
 * The on/off switch a programme rule offers here. Anything beyond enable and disable
 * (activate from shadow, delete, restore) is the rules screen's job, where the history
 * sits next to it.
 */
function toggleActionFor(state: string): RuleActionWord | null {
  if (state === "active") return "disable";
  if (state === "disabled") return "enable";
  return null;
}

export default function ScopesPage() {
  const [scopes, setScopes] = React.useState<Scope[] | null>(null);
  const [rules, setRules] = React.useState<ProgrammeRule[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [fresh, setFresh] = React.useState({ ...NEW_SCOPE });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      // One request fetches every programme's rules; the cards split them by code.
      const [loadedScopes, loadedRules] = await Promise.all([
        api.listScopes(),
        api.listProgrammeRules(),
      ]);
      setScopes(loadedScopes);
      setRules(loadedRules);
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
              rules={rules.filter((rule) => rule.scope_code === scope.code)}
              busy={busy}
              onSave={(changes) =>
                void act("save the programme", () => api.saveScope({ ...scope, ...changes }))
              }
              onDelete={(confirm) =>
                void act("delete the programme", () => api.deleteScope(scope.code, confirm))
              }
              onChanged={() => void load()}
              onAct={act}
            />
          ))}
        </div>
      )}
    </>
  );
}

/** What a card needs to run a request through the page's busy and error handling. */
type Act = (what: string, run: () => Promise<unknown>) => Promise<void>;

/** One programme, with its keywords, standing instructions, and rules. */
function ScopeCard({
  scope,
  rules,
  busy,
  onSave,
  onDelete,
  onAct,
  onChanged,
}: {
  scope: Scope;
  rules: ProgrammeRule[];
  busy: boolean;
  onSave: (changes: Partial<Scope>) => void;
  onDelete: (confirm: string) => void;
  onAct: Act;
  onChanged: () => void;
}) {
  const [label, setLabel] = React.useState(scope.label);
  const [description, setDescription] = React.useState(scope.description);
  const [instructions, setInstructions] = React.useState(scope.standing_instructions);
  const [secondApprover, setSecondApprover] = React.useState(scope.second_approver);
  const [keywords, setKeywords] = React.useState(scope.keywords.join(", "));
  const [showVersions, setShowVersions] = React.useState(false);

  return (
    <Card className="border-l-4 border-l-primary bg-accent/20">
      <CardHeader className="flex-row items-center justify-between border-b">
        <div className="flex items-center gap-2">
          <CardTitle className="flex items-center gap-2">
            <span className="mono rounded bg-primary px-1.5 py-0.5 text-xs text-primary-foreground">
              {scope.code}
            </span>
            {scope.label}
          </CardTitle>
          <Badge tone="outline" title="Version of the rule set">
            {versionLabel(scope.version)}
          </Badge>
          {scope.is_active ? null : <Badge tone="muted">off</Badge>}
          {scope.runs_using > 0 ? <Badge tone="muted">{scope.runs_using} run(s)</Badge> : null}
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Versions of ${scope.label} rules`}
            onClick={() => setShowVersions(!showVersions)}
          >
            {showVersions ? "Hide versions" : "Rule versions"}
          </Button>
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
          <DeleteButton
            label={`programme ${scope.label}`}
            busy={busy}
            disabled={scope.runs_using > 0}
            onDelete={(confirm) => onDelete(confirm)}
          />
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 pt-3">
        {showVersions ? (
          <VersionsPanel kind="programme" objectKey={scope.code} onReverted={onChanged} />
        ) : null}
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
          <Label htmlFor={`sk-${scope.code}`}>Keywords</Label>
          <Input
            id={`sk-${scope.code}`}
            placeholder="solicitation, prescreen, firm offer"
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
          />
          <span className="text-[0.7rem] text-muted-foreground">
            Comma-separated. The tool greps the OSL, the configuration, and the report headers for
            these to confirm a run really is this programme; a run declared as this programme with
            none of them gets a finding. A grep by code; the words are not sent to the model.
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1">
            <Label htmlFor={`si-${scope.code}`}>Standing instructions</Label>
            <Explain label="What standing instructions are for">
              The compliance expectations that are true of every run in this programme and that the
              OSL usually does not restate — the context a new reviewer would be told on their first
              day.
              <br />
              <br />
              Not a rule: something that must hold belongs in a programme rule below, where code
              grades it. Narrower than a programme? A note on one configuration. About one document
              rather than one programme? That artifact type&rsquo;s AI context.
            </Explain>
          </div>
          <Textarea
            id={`si-${scope.code}`}
            rows={3}
            placeholder="Compliance expectations true of every run in this programme. Leave empty and nothing is added to the prompts."
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
          />
          <FieldEffect
            kind="model"
            note="Background for every run in this programme. It never makes anything pass or fail; the OSL stays the source of truth."
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={secondApprover}
              onChange={(event) => setSecondApprover(event.target.checked)}
            />
            <span className="font-medium">
              A second person approves what a reviewer waves through
            </span>
          </label>
          <span className="text-[0.7rem] text-muted-foreground">
            With this on, a run in this programme cannot be frozen when the reviewer marked OK a
            breach of a <span className="mono">must</span> rule or a missing compliance rule, until
            someone else signs. It is a signature, not a re-review, and it has to be someone other
            than the reviewer. <b>It does nothing while login is off</b>, because everyone is then
            the same placeholder account — the rule stands down rather than making the run
            impossible to finalize (ADR-036).
          </span>
        </div>
        <div>
          <Button
            disabled={busy}
            onClick={() =>
              onSave({
                label,
                description,
                standing_instructions: instructions,
                keywords: parseKeywords(keywords),
                second_approver: secondApprover,
              })
            }
          >
            Save
          </Button>
        </div>
        <ProgrammeRules scope={scope} rules={rules} busy={busy} onAct={onAct} />
      </CardContent>
    </Card>
  );
}

/** The rules of one programme: the list, an inline editor, and the add form. */
function ProgrammeRules({
  scope,
  rules,
  busy,
  onAct,
}: {
  scope: Scope;
  rules: ProgrammeRule[];
  busy: boolean;
  onAct: Act;
}) {
  const [adding, setAdding] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [confirmingId, setConfirmingId] = React.useState<number | null>(null);

  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Programme rules</span>
        <Button size="xs" variant="outline" disabled={busy} onClick={() => setAdding(!adding)}>
          <Plus className="h-3.5 w-3.5" /> Add a rule
        </Button>
      </div>
      <span className="text-[0.7rem] text-muted-foreground">
        The model reads each delivery against these and names what it breaks. The strictness decides
        how serious a breach is, and code applies it: must is a high finding, should medium,
        advisory low.
      </span>

      {adding ? (
        <RuleForm
          idPrefix={`pr-new-${scope.code}`}
          busy={busy}
          submitLabel="Add rule"
          onCancel={() => setAdding(false)}
          onSubmit={(draft) =>
            void onAct("add the rule", async () => {
              await api.createProgrammeRule({ ...draft, scope_code: scope.code });
              setAdding(false);
            })
          }
        />
      ) : null}

      {rules.length === 0 && !adding ? (
        <p className="text-xs text-muted-foreground">No rules yet for this programme.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rules.map((rule) => {
            const toggle = toggleActionFor(rule.state);
            return (
              <li key={rule.id} className="rounded-md border p-2">
                {editingId === rule.id ? (
                  <RuleForm
                    idPrefix={`pr-${rule.id}`}
                    initial={rule}
                    busy={busy}
                    submitLabel="Save rule"
                    onCancel={() => setEditingId(null)}
                    onSubmit={(draft) =>
                      void onAct("save the rule", async () => {
                        await api.updateProgrammeRule(rule.id, {
                          ...draft,
                          scope_code: scope.code,
                          sort_order: rule.sort_order,
                        });
                        setEditingId(null);
                      })
                    }
                  />
                ) : (
                  <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium">{rule.title}</span>
                      <Badge tone={STRICTNESS_TONES[rule.strictness]}>{rule.strictness}</Badge>
                      <Badge tone={STATE_TONES[rule.state] ?? "muted"}>{rule.state}</Badge>
                      <div className="ml-auto flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="xs"
                          disabled={busy}
                          aria-label={`Edit ${rule.title}`}
                          onClick={() => {
                            setConfirmingId(null);
                            setEditingId(rule.id);
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" /> Edit
                        </Button>
                        {toggle ? (
                          <Button
                            variant="outline"
                            size="xs"
                            disabled={busy}
                            onClick={() =>
                              setConfirmingId(confirmingId === rule.id ? null : rule.id)
                            }
                          >
                            {toggle}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <p className="whitespace-pre-wrap text-xs text-muted-foreground">{rule.text}</p>
                    {toggle && confirmingId === rule.id ? (
                      <ConfirmAction
                        id={`pr-confirm-${rule.id}`}
                        action={toggle}
                        busy={busy}
                        onCancel={() => setConfirmingId(null)}
                        onConfirm={(confirm) =>
                          void onAct(`${toggle} the rule`, async () => {
                            await api.actOnRule("programme_rule", rule.id, toggle, confirm);
                            setConfirmingId(null);
                          })
                        }
                      />
                    ) : null}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** The fields an administrator writes for a rule; the programme is the card's. */
type RuleDraft = Omit<ProgrammeRuleIn, "scope_code" | "sort_order">;

/** One form for both adding and editing, so the two never drift apart. */
function RuleForm({
  idPrefix,
  initial,
  busy,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  idPrefix: string;
  initial?: RuleDraft;
  busy: boolean;
  submitLabel: string;
  onSubmit: (draft: RuleDraft) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = React.useState(initial?.title ?? "");
  const [text, setText] = React.useState(initial?.text ?? "");
  const [strictness, setStrictness] = React.useState<Strictness>(
    initial?.strictness ?? DEFAULT_STRICTNESS
  );

  return (
    <div className="grid gap-2 rounded-md border bg-muted/40 p-2">
      <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-title`}>Title</Label>
          <Input
            id={`${idPrefix}-title`}
            placeholder="Opt-out list honoured"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${idPrefix}-strictness`}>Strictness</Label>
          <Select
            id={`${idPrefix}-strictness`}
            value={strictness}
            onChange={(event) => setStrictness(event.target.value as Strictness)}
          >
            {STRICTNESS_LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${idPrefix}-text`}>Rule</Label>
        <Textarea
          id={`${idPrefix}-text`}
          rows={2}
          placeholder="What every delivery in this programme has to do, in plain words."
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </div>
      <div className="flex gap-1.5">
        <Button
          size="xs"
          disabled={busy || !title.trim() || !text.trim()}
          onClick={() => onSubmit({ title: title.trim(), text: text.trim(), strictness })}
        >
          {submitLabel}
        </Button>
        <Button size="xs" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * The typed confirmation, as on the rules screen. The administrator types the action
 * word rather than clicking twice, because a rule change reaches every future run,
 * and the API enforces the same word with a 400.
 */
function ConfirmAction({
  id,
  action,
  busy,
  onConfirm,
  onCancel,
}: {
  id: string;
  action: RuleActionWord;
  busy: boolean;
  onConfirm: (confirm: string) => void;
  onCancel: () => void;
}) {
  const [typed, setTyped] = React.useState("");

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-muted/40 p-2">
      <Label htmlFor={id}>
        Type <span className="mono font-semibold">{action}</span> to confirm
      </Label>
      <Input
        id={id}
        className="mono h-7 w-32 text-xs"
        autoComplete="off"
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
      <Button
        size="xs"
        disabled={busy || typed.trim() !== action}
        onClick={() => onConfirm(typed.trim())}
      >
        {action}
      </Button>
      <Button size="xs" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

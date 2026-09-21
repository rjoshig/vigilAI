"use client";

/**
 * What this delivery calls each name the fixed checks look for (Phase 6.21b, ADR-051).
 *
 * The checks ask for `Attributes`, `States`, `Accepts`. Until Phase 6.21 those were
 * Python constants matched exactly, so a customer who names their sheets differently
 * got a page of "could not evaluate" and no validation at all — and fixing it meant a
 * deploy.
 *
 * An entry here is read by the resolver's *fourth* rung, which is the one a person
 * writes. That placement is the design: it is reached only after exact,
 * separator-insensitive and same-words matching have all failed, it never overrules
 * the name actually asked for, and it costs no model call. Recording one turns a
 * delivery the AI had to reason about into a delivery code resolves.
 *
 * The suggestions below are what the AI already read, on runs that have happened.
 * Accepting one is what closes the loop.
 */

import { Check, Plus, Sparkles, Trash2 } from "lucide-react";
import * as React from "react";

import { FieldEffect } from "@/components/explain";
import { ScopePicker } from "@/components/scope-picker";
import { Badge, Button, Input, Label, Select } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ArtifactType, LayoutEntry, LayoutKind, LayoutSuggestion, Scope } from "@/lib/types";

interface LayoutEditorProps {
  type: ArtifactType;
  busy: boolean;
  onSaved: (type: ArtifactType) => void;
}

/** What each kind means, in the words somebody setting this up would use. */
const KINDS: { value: LayoutKind; label: string; hint: string }[] = [
  { value: "sheet", label: "Worksheet", hint: "a tab in the workbook" },
  { value: "column", label: "Column heading", hint: "a heading on the header row" },
  { value: "label", label: "Row label", hint: "the text in a row's first column" },
];

/** The names the shipped checks look for, so nobody has to remember them. */
const WANTED: Record<string, string[]> = {
  sheet: ["Attributes", "States", "Fields", "Flow"],
  column: ["Attribute", "Min", "Max", "State", "Field"],
  label: ["Accepts", "Rejects", "Input"],
};

function blank(): LayoutEntry {
  return { scope: "", kind: "sheet", wanted: "", names: [], note: "", added_by: "" };
}

export function LayoutEditor({ type, busy, onSaved }: LayoutEditorProps) {
  const [entries, setEntries] = React.useState<LayoutEntry[]>(type.layout);
  // What is in the spellings box, verbatim. The parsed list is derived from it,
  // never the other way round: deriving the box from the list would re-join on
  // every keystroke and eat the space somebody just typed.
  const [drafts, setDrafts] = React.useState<string[]>(() =>
    type.layout.map((entry) => entry.names.join(", "))
  );
  const [suggestions, setSuggestions] = React.useState<LayoutSuggestion[]>([]);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setEntries(type.layout);
    setDrafts(type.layout.map((entry) => entry.names.join(", ")));
  }, [type.layout]);

  const loadSuggestions = React.useCallback(() => {
    api
      .getLayoutSuggestions()
      .then((result) =>
        setSuggestions(result.suggestions.filter((row) => row.artifact === type.key))
      )
      // No opinion rather than an obstacle: the editor works without them.
      .catch(() => setSuggestions([]));
  }, [type.key]);

  React.useEffect(loadSuggestions, [loadSuggestions]);

  React.useEffect(() => {
    // Same rule as the suggestions: the editor works without them, and a scope
    // typed by hand is still a scope.
    api
      .listScopes()
      .then(setProgrammes)
      .catch(() => setProgrammes([]));
  }, []);

  function update(index: number, changes: Partial<LayoutEntry>) {
    setEntries(entries.map((entry, i) => (i === index ? { ...entry, ...changes } : entry)));
  }

  /** Read the spellings box: keep the text, and derive the list the API is sent. */
  function setNames(index: number, text: string) {
    setDrafts(drafts.map((draft, i) => (i === index ? text : draft)));
    update(index, {
      names: text
        .split(",")
        .map((name) => name.trim())
        .filter(Boolean),
    });
  }

  async function save() {
    setSaving(true);
    try {
      onSaved(
        await api.saveLayout(
          type.key,
          entries.filter((entry) => entry.wanted.trim() && entry.names.length > 0)
        )
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the layout.");
    } finally {
      setSaving(false);
    }
  }

  async function accept(suggestion: LayoutSuggestion) {
    setSaving(true);
    try {
      onSaved(
        await api.acceptLayout(
          suggestion.artifact,
          suggestion.kind,
          suggestion.wanted,
          suggestion.found
        )
      );
      loadSuggestions();
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not record that name.");
    } finally {
      setSaving(false);
    }
  }

  const pending = suggestions.filter((row) => !row.already_listed);

  return (
    <div className="grid gap-3 py-2" data-testid={`layout-${type.key}`}>
      <p className="text-[0.7rem] text-muted-foreground">
        The checks look for a worksheet called <b>Attributes</b>, a row labelled <b>Accepts</b>, and
        so on. Where this delivery words one differently, say so here and the checks find it in
        code. Spelling, separators and plurals are already handled — you only need an entry when the
        words themselves differ.
      </p>
      <FieldEffect
        kind="code"
        note="Compared against the uploaded reports before any model call."
      />

      {pending.length > 0 ? (
        <div className="grid gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <Sparkles className="h-3.5 w-3.5" />
            The AI read {pending.length} name{pending.length === 1 ? "" : "s"} for you
          </div>
          <p className="text-[0.7rem] text-muted-foreground">
            On these runs no rule of spelling reached the name, so the AI was shown the names this
            delivery carries and asked which was meant. Each one was checked against that list and
            is already on the run as something to confirm. Recording it here means the next run
            finds it without asking.
          </p>
          {pending.map((suggestion) => (
            <div
              key={`${suggestion.kind}-${suggestion.wanted}-${suggestion.found}`}
              className="flex flex-wrap items-center gap-2 rounded-md border bg-card p-2 text-xs"
            >
              <Badge tone="muted">{suggestion.kind}</Badge>
              <span>
                <b>{suggestion.wanted}</b> → <b>{suggestion.found}</b>
              </span>
              <Badge tone="muted">{Math.round(suggestion.confidence * 100)}% sure</Badge>
              <Badge tone="muted">
                {suggestion.seen} run{suggestion.seen === 1 ? "" : "s"}
              </Badge>
              <span className="text-muted-foreground">{suggestion.reason}</span>
              <Button
                size="xs"
                className="ml-auto"
                disabled={busy || saving}
                onClick={() => void accept(suggestion)}
              >
                <Check className="mr-1 h-3.5 w-3.5" />
                Record it
              </Button>
            </div>
          ))}
        </div>
      ) : null}

      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Nothing recorded, which is the ordinary state: most deliveries are read without one.
        </p>
      ) : null}

      {entries.map((entry, index) => (
        <div key={index} className="grid gap-2 rounded-md border bg-card p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">
              Entry {index + 1}
              {entry.added_by ? (
                <Badge tone="muted" className="ml-2">
                  {entry.note || "added"} · {entry.added_by}
                </Badge>
              ) : null}
            </span>
            <Button
              variant="ghost"
              size="xs"
              aria-label={`Remove entry ${index + 1}`}
              onClick={() => {
                setEntries(entries.filter((_, i) => i !== index));
                setDrafts(drafts.filter((_, i) => i !== index));
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor={`l-${type.key}-${index}-kind`}>What kind</Label>
              <Select
                id={`l-${type.key}-${index}-kind`}
                value={entry.kind}
                onChange={(event) =>
                  update(index, { kind: event.target.value as LayoutKind, wanted: "" })
                }
              >
                {KINDS.map((kind) => (
                  <option key={kind.value} value={kind.value}>
                    {kind.label} — {kind.hint}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`l-${type.key}-${index}-wanted`}>The checks look for</Label>
              <Input
                id={`l-${type.key}-${index}-wanted`}
                list={`l-${type.key}-${index}-wanted-options`}
                value={entry.wanted}
                placeholder="Attributes"
                onChange={(event) => update(index, { wanted: event.target.value })}
              />
              <datalist id={`l-${type.key}-${index}-wanted-options`}>
                {(WANTED[entry.kind] ?? []).map((name) => (
                  <option key={name} value={name} />
                ))}
              </datalist>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`l-${type.key}-${index}-names`}>This delivery calls it</Label>
              <Input
                id={`l-${type.key}-${index}-names`}
                value={drafts[index] ?? ""}
                placeholder="Attribute Summary"
                onChange={(event) => setNames(index, event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`l-${type.key}-${index}-scope-kind`}>Where it applies</Label>
              <ScopePicker
                idPrefix={`l-${type.key}-${index}-scope`}
                programmes={programmes}
                value={entry.scope}
                onChange={(scope) => update(index, { scope })}
                disabled={busy || saving}
              />
            </div>
          </div>
          {entry.names.length > 1 ? (
            <p className="text-[0.7rem] text-muted-foreground">
              Any of these counts. Several is right when customers in this scope word it differently
              from each other.
            </p>
          ) : null}
        </div>
      ))}

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      <div className="flex gap-2">
        <Button
          size="xs"
          variant="outline"
          onClick={() => {
            setEntries([...entries, blank()]);
            setDrafts([...drafts, ""]);
          }}
          disabled={busy || saving}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          Add a name
        </Button>
        <Button size="xs" onClick={() => void save()} disabled={busy || saving}>
          {saving ? "Saving…" : "Save layout"}
        </Button>
      </div>
    </div>
  );
}

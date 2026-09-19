"use client";

/**
 * Standing notes on an ETL configuration (ADR-024, 6.4b).
 *
 * A note is guidance: it reaches the model as background on every future run of the
 * configuration and lands in the admin queue, where an administrator may turn it into
 * a rule. On its own it never makes anything pass or fail. The panel shows what is
 * already in force first, so a person adds to it rather than writing a second one.
 * It carries no Train AI tag because notes exist whatever the mode says.
 */

import { History, Pencil, Plus, Power, StickyNote } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  ErrorState,
  Label,
  Select,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ConfigNoteInput, Observation, Severity } from "@/lib/types";
import { cn, fmtTime } from "@/lib/utils";

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "review", label: "Needs a person to look" },
];

/** What a note does, said once beside every place one can be written. */
const NOTE_HELP =
  "A note reaches the model as background on every future run of this configuration and can be reviewed by an administrator; it never makes anything pass or fail on its own.";

const MIN_STATEMENT = 3;

export interface ConfigNotesProps {
  /** The ETL configuration the notes follow. Nothing is fetched while it is blank. */
  configurationId: string;
  /**
   * "add" shows the notes in force and lets a person add one, for the new-run form.
   * "manage" also allows editing, switching off and on, and reading earlier wordings,
   * for the config history page.
   */
  mode: "add" | "manage";
  className?: string;
}

export function ConfigNotes({ configurationId, mode, className }: ConfigNotesProps) {
  const [notes, setNotes] = React.useState<Observation[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<Observation | null>(null);
  const [showInactive, setShowInactive] = React.useState(false);

  const manage = mode === "manage";

  const load = React.useCallback(async () => {
    if (!configurationId) {
      setNotes(null);
      return;
    }
    try {
      setNotes(await api.listConfigNotes(configurationId, manage && showInactive));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load the notes.");
    }
  }, [configurationId, manage, showInactive]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function toggle(note: Observation) {
    try {
      const stored = await api.setConfigNoteActive(note.id, !note.is_active);
      setNotes((prev) => (prev ?? []).map((item) => (item.id === stored.id ? stored : item)));
      // A note switched off disappears from the in-force list unless history is shown.
      if (!showInactive) void load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not change that note.");
    }
  }

  if (!configurationId) return null;

  const inForce = (notes ?? []).filter((note) => note.is_active);
  const switchedOff = (notes ?? []).filter((note) => !note.is_active);

  return (
    <div className={cn("flex flex-col gap-2 text-xs", className)}>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {notes === null && !error ? <Skeleton className="h-10" /> : null}

      {notes !== null ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">
              {inForce.length === 0
                ? "No notes on this configuration yet."
                : `${inForce.length} note${inForce.length === 1 ? "" : "s"} in force`}
            </span>
            {manage ? (
              <label className="flex items-center gap-1.5 text-[0.7rem] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={showInactive}
                  onChange={(event) => setShowInactive(event.target.checked)}
                />
                Show switched-off notes
              </label>
            ) : null}
          </div>

          {inForce.map((note) => (
            <NoteRow
              key={note.id}
              note={note}
              manage={manage}
              onEdit={() => setEditing(note)}
              onToggle={() => void toggle(note)}
            />
          ))}

          {manage && showInactive && switchedOff.length > 0 ? (
            <>
              <div className="pt-1 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                Switched off
              </div>
              {switchedOff.map((note) => (
                <NoteRow
                  key={note.id}
                  note={note}
                  manage={manage}
                  onEdit={() => setEditing(note)}
                  onToggle={() => void toggle(note)}
                />
              ))}
            </>
          ) : null}
        </>
      ) : null}

      {editing ? (
        <NoteForm
          existing={editing}
          configurationId={configurationId}
          onCancel={() => setEditing(null)}
          onSaved={(stored) => {
            setEditing(null);
            setNotes((prev) => (prev ?? []).map((item) => (item.id === stored.id ? stored : item)));
          }}
        />
      ) : adding ? (
        <NoteForm
          configurationId={configurationId}
          onCancel={() => setAdding(false)}
          onSaved={(stored) => {
            setAdding(false);
            setNotes((prev) => [...(prev ?? []), stored]);
          }}
        />
      ) : (
        <div>
          <Button variant="outline" size="xs" onClick={() => setAdding(true)}>
            <Plus className="h-3.5 w-3.5" /> Add a note for this configuration
          </Button>
        </div>
      )}
    </div>
  );
}

interface NoteRowProps {
  note: Observation;
  manage: boolean;
  onEdit: () => void;
  onToggle: () => void;
}

function NoteRow({ note, manage, onEdit, onToggle }: NoteRowProps) {
  const [history, setHistory] = React.useState(false);

  return (
    <div
      className={cn("rounded-md border bg-muted/40 px-2.5 py-2", !note.is_active && "opacity-70")}
    >
      <div className="flex flex-wrap items-start gap-2">
        <StickyNote className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-primary" />
        <span className="min-w-[10rem] flex-1">{note.statement}</span>
        {manage ? (
          <span className="flex items-center gap-1">
            {note.revisions.length > 0 ? (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setHistory((open) => !open)}
                title="Earlier wordings of this note"
              >
                <History className="h-3.5 w-3.5" /> {history ? "Hide" : "History"}
              </Button>
            ) : null}
            <Button variant="ghost" size="xs" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Button>
            <Button
              variant="ghost"
              size="xs"
              onClick={onToggle}
              title={
                note.is_active
                  ? "Stop this note reaching the model on the next run; the text is kept"
                  : "Apply this note again from the next run"
              }
            >
              <Power className="h-3.5 w-3.5" /> {note.is_active ? "Switch off" : "Switch on"}
            </Button>
          </span>
        ) : null}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[0.7rem] text-muted-foreground">
        <span>{note.author || "unknown"}</span>
        <span>· v{note.version}</span>
        <span>· {fmtTime(note.created_at)}</span>
        <Badge tone="muted" className="px-1.5 py-0 text-[0.625rem]">
          {note.severity_hint}
        </Badge>
        {!note.is_active ? (
          <Badge tone="outline" className="px-1.5 py-0 text-[0.625rem]">
            switched off
          </Badge>
        ) : null}
      </div>

      {history && note.revisions.length > 0 ? (
        <ol className="mt-2 flex flex-col gap-1 border-l-2 pl-2.5 text-[0.7rem]">
          {note.revisions.map((revision) => (
            <li key={revision.version}>
              <span className="text-muted-foreground">
                v{revision.version} · {revision.by || "unknown"} · {fmtTime(revision.at)}
              </span>
              <div>{revision.statement}</div>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

interface NoteFormProps {
  configurationId: string;
  /** Set when the form rewords a note rather than writing a new one. */
  existing?: Observation;
  onCancel: () => void;
  onSaved: (note: Observation) => void;
}

function NoteForm({ configurationId, existing, onCancel, onSaved }: NoteFormProps) {
  const [statement, setStatement] = React.useState(existing?.statement ?? "");
  const [severity, setSeverity] = React.useState<Severity>(existing?.severity_hint ?? "medium");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const idPrefix = existing ? `config-note-${existing.id}` : "config-note-new";

  async function save() {
    setSaving(true);
    setError(null);
    const body: ConfigNoteInput = { statement: statement.trim(), severity_hint: severity };
    try {
      const stored = existing
        ? await api.updateConfigNote(existing.id, body)
        : await api.createConfigNote(configurationId, body);
      onSaved(stored);
    } catch (caught) {
      // The 422 text names what to take out before saving, so it is shown as written.
      setError(caught instanceof ApiError ? caught.detail : "Could not save that note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border p-2.5">
      {error ? <ErrorState message={error} /> : null}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-statement`}>
          {existing ? "Reword the note" : "What should the model know about this configuration?"}
          <span className="text-destructive"> *</span>
        </Label>
        <Textarea
          id={`${idPrefix}-statement`}
          value={statement}
          onChange={(event) => setStatement(event.target.value)}
          placeholder="For example: this configuration delivers state codes as two letters, not names."
        />
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idPrefix}-severity`}>How much weight should it carry?</Label>
          <Select
            id={`${idPrefix}-severity`}
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity)}
          >
            {SEVERITIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
        <span className="ml-auto flex gap-1.5">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={statement.trim().length < MIN_STATEMENT || saving}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : existing ? "Save wording" : "Save note"}
          </Button>
        </span>
      </div>
      <span className="text-[0.7rem] text-muted-foreground">
        {NOTE_HELP} Write no account numbers, names, or other personal data; saving is refused when
        the text looks like it carries any.
      </span>
    </div>
  );
}

"use client";

/**
 * The validation guide of one artifact type (Phase 6.8b, ADR-029).
 *
 * Each entry names a cell or a label in the report, says what it means, points at
 * the OSL and the configuration, and says what to validate. The model reads the
 * guide as background; an entry with a config path and a comparison that resolves on
 * a sample also becomes a check, born in shadow, on the Rules screen.
 */

import { Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { FieldEffect } from "@/components/explain";
import { Badge, Button, Input, Label, Select, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ArtifactType, GuideComparison, GuideEntry } from "@/lib/types";

interface GuideEditorProps {
  type: ArtifactType;
  busy: boolean;
  onSaved: (type: ArtifactType) => void;
}

function blankEntry(sheet: string, index: number): GuideEntry {
  return {
    id: `entry-${index}`,
    locator: { kind: "label", sheet, cell: "", label: "", label_column: 0, value_column: 1 },
    meaning: "",
    osl_section: "",
    osl_phrase: "",
    config_path: "",
    validate: "",
    comparison: "",
    tolerance: 0,
    examples: [],
  };
}

/** A stable, expression-safe id from the meaning, so the check has a readable name. */
function slug(text: string, fallback: string): string {
  const cleaned = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return cleaned || fallback;
}

export function GuideEditor({ type, busy, onSaved }: GuideEditorProps) {
  const [entries, setEntries] = React.useState<GuideEntry[]>(type.guide);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setEntries(type.guide), [type.guide]);

  function update(index: number, changes: Partial<GuideEntry>) {
    setEntries(entries.map((entry, i) => (i === index ? { ...entry, ...changes } : entry)));
  }

  function updateLocator(index: number, changes: Partial<GuideEntry["locator"]>) {
    const entry = entries[index];
    update(index, { locator: { ...entry.locator, ...changes } });
  }

  async function save() {
    setSaving(true);
    try {
      const payload = entries.map((entry, index) => ({
        ...entry,
        id: slug(entry.meaning, entry.id || `entry-${index + 1}`),
        tolerance: entry.comparison === "reconciles" ? entry.tolerance : 0,
      }));
      onSaved(await api.saveGuide(type.key, payload));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not save the guide.");
    } finally {
      setSaving(false);
    }
  }

  const compiled = type.guide.filter(
    (entry) => entry.config_path && entry.comparison && entry.examples.length > 0
  ).length;

  return (
    <div className="grid gap-3 py-2" data-testid={`guide-${type.key}`}>
      <p className="text-[0.7rem] text-muted-foreground">
        Sent to the model as background on every run; code does the comparing. An entry with a
        configuration path and a comparison that resolves on a sample also becomes a check, born in
        shadow, on the Rules screen.
        {type.guide.length > 0
          ? ` ${compiled} of ${type.guide.length} entries compile to checks.`
          : ""}
      </p>
      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">No entries yet.</p>
      ) : null}
      {entries.map((entry, index) => (
        <div key={index} className="grid gap-2 rounded-md border bg-card p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">
              Entry {index + 1}
              {entry.examples.length > 0 ? (
                <Badge tone="muted" className="ml-2">
                  resolves on {entry.examples.length} sample(s)
                </Badge>
              ) : null}
            </span>
            <Button
              variant="ghost"
              size="xs"
              aria-label={`Remove entry ${index + 1}`}
              onClick={() => setEntries(entries.filter((_, i) => i !== index))}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-sheet`}>Sheet</Label>
              <Select
                id={`g-${type.key}-${index}-sheet`}
                value={entry.locator.sheet}
                onChange={(event) => updateLocator(index, { sheet: event.target.value })}
              >
                <option value="">(first sheet)</option>
                {type.sheets.map((sheet) => (
                  <option key={sheet} value={sheet}>
                    {sheet}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-kind`}>Point at</Label>
              <Select
                id={`g-${type.key}-${index}-kind`}
                value={entry.locator.kind}
                onChange={(event) =>
                  updateLocator(index, { kind: event.target.value as "cell" | "label" })
                }
              >
                <option value="label">A label, value beside it</option>
                <option value="cell">A cell address</option>
              </Select>
            </div>
            {entry.locator.kind === "label" ? (
              <>
                <div className="flex flex-col gap-1">
                  <Label htmlFor={`g-${type.key}-${index}-label`}>Label text</Label>
                  <Input
                    id={`g-${type.key}-${index}-label`}
                    placeholder="Accepts"
                    value={entry.locator.label}
                    onChange={(event) => updateLocator(index, { label: event.target.value })}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor={`g-${type.key}-${index}-col`}>Value column (0 = A)</Label>
                  <Input
                    id={`g-${type.key}-${index}-col`}
                    type="number"
                    min={0}
                    value={entry.locator.value_column}
                    onChange={(event) =>
                      updateLocator(index, { value_column: Number(event.target.value) })
                    }
                  />
                </div>
              </>
            ) : (
              <div className="flex flex-col gap-1 sm:col-span-2">
                <Label htmlFor={`g-${type.key}-${index}-cell`}>Cell</Label>
                <Input
                  id={`g-${type.key}-${index}-cell`}
                  className="mono"
                  placeholder="D8"
                  value={entry.locator.cell}
                  onChange={(event) => updateLocator(index, { cell: event.target.value })}
                />
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`g-${type.key}-${index}-meaning`}>What it means</Label>
            <Input
              id={`g-${type.key}-${index}-meaning`}
              placeholder="The delivered record count"
              value={entry.meaning}
              onChange={(event) => update(index, { meaning: event.target.value })}
            />
            <FieldEffect
              kind="model"
              note="Read by the model when it traces a requirement into this report and when it checks a finding, so it knows what a cell is for rather than guessing from its label. A complete entry also compiles into a check that code runs."
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-osl-s`}>OSL section</Label>
              <Input
                id={`g-${type.key}-${index}-osl-s`}
                placeholder="6"
                value={entry.osl_section}
                onChange={(event) => update(index, { osl_section: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-osl-p`}>OSL phrase</Label>
              <Input
                id={`g-${type.key}-${index}-osl-p`}
                placeholder="the billing paragraph"
                value={entry.osl_phrase}
                onChange={(event) => update(index, { osl_phrase: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-cfg`}>Configuration path</Label>
              <Input
                id={`g-${type.key}-${index}-cfg`}
                className="mono"
                placeholder="waterfall.steps[3].count"
                value={entry.config_path}
                onChange={(event) => update(index, { config_path: event.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-validate`}>What to validate</Label>
              <Textarea
                id={`g-${type.key}-${index}-validate`}
                rows={2}
                placeholder="The delivered count must equal the count the configuration sets."
                value={entry.validate}
                onChange={(event) => update(index, { validate: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-cmp`}>Code checks</Label>
              <Select
                id={`g-${type.key}-${index}-cmp`}
                value={entry.comparison}
                disabled={!entry.config_path.trim()}
                onChange={(event) =>
                  update(index, { comparison: event.target.value as GuideComparison })
                }
              >
                <option value="">Nothing (explanation only)</option>
                <option value="equals">Report equals the configuration value</option>
                <option value="reconciles">Reconciles within a tolerance</option>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor={`g-${type.key}-${index}-tol`}>Tolerance (fraction)</Label>
              <Input
                id={`g-${type.key}-${index}-tol`}
                type="number"
                min={0}
                step={0.01}
                disabled={entry.comparison !== "reconciles"}
                value={entry.tolerance}
                onChange={(event) => update(index, { tolerance: Number(event.target.value) })}
              />
            </div>
          </div>
          {entry.examples.length > 0 ? (
            <p className="text-[0.7rem] text-muted-foreground">
              In the samples:{" "}
              {entry.examples.map((example) => (
                <span key={example.sample_id} className="mono mr-2">
                  {example.label || `#${example.sample_id}`} = {example.value}
                </span>
              ))}
            </p>
          ) : null}
        </div>
      ))}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="xs"
          onClick={() =>
            setEntries([...entries, blankEntry(type.sheets[0] ?? "", entries.length + 1)])
          }
        >
          <Plus className="h-3.5 w-3.5" /> Add entry
        </Button>
        <Button disabled={busy || saving} onClick={() => void save()}>
          Save guide
        </Button>
      </div>
    </div>
  );
}

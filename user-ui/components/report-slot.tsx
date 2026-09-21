"use client";

/**
 * One output-report upload slot, which may hold more than one file.
 *
 * Some campaigns deliver the same report type several times: one field distribution
 * per segment, per state, or per deliverable (ADR-021, milestone 6.1b). A slot is
 * therefore a list of parts rather than a single file. One file stays the ordinary
 * case and is drawn exactly as it was, so the form does not become a wall of drop
 * zones for the person who has one of each.
 */

import { Plus, X } from "lucide-react";
import * as React from "react";

import { FileDrop } from "@/components/file-drop";
import { Button, Input } from "@/components/ui/primitives";
import type { DetectionVerdict, ArtifactSlot, TypeDetection } from "@/lib/types";

/** One file inside a slot, with the name its uploader gives it. */
export interface ReportPart {
  /** Stable across re-renders so React keys and the move controls agree. */
  id: string;
  file: File | null;
  label: string;
  detection: TypeDetection | null;
  detecting: boolean;
}

/** An empty part, which is what an "Add another file" press produces. */
export function emptyPart(): ReportPart {
  return {
    id: `part-${Math.random().toString(36).slice(2)}`,
    file: null,
    label: "",
    detection: null,
    detecting: false,
  };
}

export interface ReportSlotFieldProps {
  slot: ArtifactSlot;
  parts: ReportPart[];
  /** The other report slots, offered when detection says the file belongs elsewhere. */
  targets: ArtifactSlot[];
  onFile: (partId: string, file: File | null) => void;
  onLabel: (partId: string, label: string) => void;
  onAdd: () => void;
  onRemove: (partId: string) => void;
  onMove: (partId: string, targetKey: string) => void;
  onDismissDetection: (partId: string) => void;
}

export function ReportSlotField({
  slot,
  parts,
  targets,
  onFile,
  onLabel,
  onAdd,
  onRemove,
  onMove,
  onDismissDetection,
}: ReportSlotFieldProps) {
  const many = parts.length > 1;

  return (
    <div className="flex flex-col gap-2 rounded-md border border-dashed p-2.5">
      {parts.map((part, index) => (
        <div key={part.id} className="flex flex-col gap-1.5">
          <FileDrop
            label={many ? `${slot.label} · file ${index + 1}` : slot.label}
            hint={part.file ? undefined : slot.description}
            accept={slot.accept}
            required={slot.is_required && index === 0}
            file={part.file}
            onChange={(file) => onFile(part.id, file)}
          />

          {many ? (
            <div className="flex items-center gap-1.5">
              <Input
                value={part.label}
                placeholder="Label this file — north, segment B, deliverable 2"
                aria-label={`Label for ${slot.label} file ${index + 1}`}
                onChange={(event) => onLabel(part.id, event.target.value)}
              />
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${slot.label} file ${index + 1}`}
                onClick={() => onRemove(part.id)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ) : null}

          {part.detecting ? (
            <span className="text-[0.7rem] text-muted-foreground">Working out what this is…</span>
          ) : null}

          {part.detection ? (
            <DetectionNote
              detection={part.detection}
              slotKey={slot.key}
              targets={targets}
              onMove={(targetKey) => onMove(part.id, targetKey)}
              onDismiss={() => onDismissDetection(part.id)}
            />
          ) : null}
        </div>
      ))}

      <Button variant="ghost" size="xs" className="self-start" onClick={onAdd}>
        <Plus className="h-3.5 w-3.5" /> Add another {slot.label.toLowerCase()} file
      </Button>
    </div>
  );
}

interface DetectionNoteProps {
  detection: TypeDetection;
  slotKey: string;
  targets: ArtifactSlot[];
  onMove: (targetKey: string) => void;
  onDismiss: () => void;
}

/**
 * What detection made of the file, and the offer to act on it.
 *
 * Nothing here reassigns a file on its own. A wrong silent assignment is worse than a
 * question, so the person always presses the button. `reason` is shown verbatim
 * because the backend writes it for a person to read.
 */
function DetectionNote({ detection, slotKey, targets, onMove, onDismiss }: DetectionNoteProps) {
  const agrees = detection.verdict === "confident" && detection.key === slotKey;
  const choices = detection.candidates.filter(
    (candidate) => candidate.key !== slotKey && targets.some((t) => t.key === candidate.key)
  );

  const sheets = detection.sheets.filter((sheet) => sheet.key && sheet.key !== slotKey);

  return (
    <div className="rounded-md border bg-muted/40 p-2 text-[0.7rem] leading-relaxed">
      {agrees ? (
        <p>
          <b>This looks like the {detection.label}.</b> {detection.reason}
        </p>
      ) : detection.verdict === "confident" ? (
        <>
          <p>
            <b>
              This looks like the {detection.label}, not the {slot(targets, slotKey)}.
            </b>{" "}
            {detection.reason}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Button size="xs" onClick={() => onMove(detection.key ?? slotKey)}>
              Move it to {detection.label}
            </Button>
            <Button size="xs" variant="ghost" onClick={onDismiss}>
              Keep it here
            </Button>
          </div>
        </>
      ) : (
        <>
          <p>
            <b>{headline(detection.verdict)}</b> {detection.reason}
          </p>
          {choices.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {choices.map((candidate) => (
                <Button
                  key={candidate.key}
                  size="xs"
                  variant="outline"
                  onClick={() => onMove(candidate.key)}
                >
                  Move to {candidate.label}
                </Button>
              ))}
              <Button size="xs" variant="ghost" onClick={onDismiss}>
                Keep it here
              </Button>
            </div>
          ) : (
            <Button className="mt-1.5" size="xs" variant="ghost" onClick={onDismiss}>
              Keep it here
            </Button>
          )}
        </>
      )}

      {sheets.length > 0 ? (
        <p className="mt-1.5 text-muted-foreground">
          Tabs that look like something else:{" "}
          {sheets.map((sheet) => `${sheet.sheet} (${sheet.label ?? sheet.key})`).join(", ")}. A
          workbook can carry several report types; upload it again in the other slot if it does.
        </p>
      ) : null}
    </div>
  );
}

function headline(verdict: DetectionVerdict): string {
  if (verdict === "reasoned") {
    // Never "this is": a tie the model broke is a reading, not a measurement, and the
    // person still presses the button (Phase 6.21e).
    return "Code could not tell these apart, so the AI read the sheet names.";
  }
  return verdict === "ambiguous"
    ? "This could be more than one thing."
    : "This did not match any known report type.";
}

/** The label of a slot by key, falling back to the key when the catalog has no label. */
function slot(slots: ArtifactSlot[], key: string): string {
  return slots.find((candidate) => candidate.key === key)?.label ?? key;
}

"use client";

/** A drag-and-drop file field for one upload slot. */

import { FileCheck2, Upload, X } from "lucide-react";
import * as React from "react";

import { Button, Label } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export interface FileDropProps {
  label: string;
  hint?: string;
  accept: string;
  required?: boolean;
  file: File | null;
  onChange: (file: File | null) => void;
}

export function FileDrop({ label, hint, accept, required, file, onChange }: FileDropProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  const inputId = React.useId();

  function accepted(candidate: File): boolean {
    const suffixes = accept.split(",").map((s) => s.trim().toLowerCase());
    return suffixes.some((suffix) => candidate.name.toLowerCase().endsWith(suffix));
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={inputId}>
        {label}
        {required ? <span className="text-destructive"> *</span> : null}
      </Label>

      {file ? (
        <div className="flex items-center justify-between gap-2 rounded-md border bg-card px-3 py-2">
          <span className="flex min-w-0 items-center gap-2 text-xs">
            <FileCheck2 className="h-4 w-4 flex-shrink-0 text-success" />
            <span className="truncate">{file.name}</span>
            <span className="flex-shrink-0 text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB
            </span>
          </span>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Remove ${file.name}`}
            onClick={() => onChange(null)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped && accepted(dropped)) onChange(dropped);
          }}
          className={cn(
            "flex min-h-[4.5rem] flex-col items-center justify-center gap-1 rounded-md border",
            "border-dashed bg-muted/40 px-3 py-3 text-xs text-muted-foreground transition-colors",
            over ? "border-primary bg-primary/5 text-foreground" : "hover:border-primary"
          )}
        >
          <Upload className="h-5 w-5 text-primary" />
          <span className="font-medium text-foreground">Drop a file or click to choose</span>
          {hint ? <span>{hint}</span> : null}
        </button>
      )}

      <input
        id={inputId}
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
    </div>
  );
}

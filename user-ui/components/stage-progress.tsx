"use client";

/** The nine-segment stage bar shown while a run is executing. */

import { STAGE_LABELS, STAGES, type StageInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEGMENT_TONE: Record<string, string> = {
  done: "bg-success",
  running: "bg-primary animate-pulse",
  failed: "bg-destructive",
  skipped: "bg-muted-foreground/40",
  pending: "bg-muted",
};

export interface StageProgressProps {
  stages: StageInfo[];
  currentStage?: string;
  compact?: boolean;
}

export function StageProgress({ stages, currentStage, compact = false }: StageProgressProps) {
  const byName = new Map(stages.map((s) => [s.stage, s]));
  const done = stages.filter((s) => s.status === "done").length;
  const active = stages.find((s) => s.status === "running") ?? byName.get(currentStage ?? "");

  return (
    <div>
      <div
        className="flex gap-0.5"
        role="img"
        aria-label={`${done} of ${STAGES.length} stages done`}
      >
        {STAGES.map((name) => {
          const stage = byName.get(name);
          const status = stage?.status ?? "pending";
          return (
            <span
              key={name}
              title={`${STAGE_LABELS[name]}: ${status}`}
              className={cn(
                "h-1.5 flex-1 rounded-sm",
                SEGMENT_TONE[status] ?? SEGMENT_TONE.pending
              )}
            />
          );
        })}
      </div>
      {!compact ? (
        <div className="mt-1.5 text-xs text-muted-foreground">
          {active && active.status !== "done"
            ? `Stage ${STAGES.indexOf(active.stage as (typeof STAGES)[number]) + 1} / 9 · ${
                STAGE_LABELS[active.stage] ?? active.stage
              }`
            : `${done} / ${STAGES.length} stages done`}
        </div>
      ) : null}
    </div>
  );
}

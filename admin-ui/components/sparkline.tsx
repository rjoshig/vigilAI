"use client";

/** A bar sparkline drawn with divs: no chart library for a strip of daily totals. */

import { cn } from "@/lib/utils";

export interface SparklineProps {
  values: { day: string; count: number }[];
  label: string;
  tone?: "primary" | "tertiary";
}

export function Sparkline({ values, label, tone = "primary" }: SparklineProps) {
  if (values.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">No data yet</p>;
  }
  const peak = Math.max(...values.map((value) => value.count), 1);

  // With one or two days of history, letting the bars flex to full width renders a
  // giant block that reads as a rendering fault rather than as data. Cap the width
  // until there are enough points for a strip to look like one.
  const sparse = values.length < 7;

  return (
    <div>
      <div
        className={cn("flex h-20 items-end gap-1", sparse && "justify-start")}
        role="img"
        aria-label={label}
      >
        {values.map((value) => (
          <div
            key={value.day}
            title={`${value.day}: ${value.count}`}
            style={{ height: `${Math.max(4, (value.count / peak) * 100)}%` }}
            className={cn(
              "rounded-t-sm",
              sparse ? "w-10" : "min-w-[4px] flex-1",
              tone === "primary" ? "bg-primary/70" : "bg-tertiary"
            )}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[0.65rem] text-muted-foreground">
        <span>{values[0].day}</span>
        {values.length > 1 ? <span>{values[values.length - 1].day}</span> : null}
      </div>
    </div>
  );
}

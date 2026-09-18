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

  return (
    <div className="flex h-20 items-end gap-0.5" role="img" aria-label={label}>
      {values.map((value) => (
        <div
          key={value.day}
          title={`${value.day}: ${value.count}`}
          style={{ height: `${Math.max(4, (value.count / peak) * 100)}%` }}
          className={cn(
            "min-w-[4px] flex-1 rounded-t-sm",
            tone === "primary" ? "bg-primary/70" : "bg-tertiary"
          )}
        />
      ))}
    </div>
  );
}

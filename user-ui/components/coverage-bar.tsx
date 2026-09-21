"use client";

/**
 * Coverage as a picture rather than four numbers (Phase 6.21f).
 *
 * The coverage panel has always been right and has always been four badges. On a run
 * with two hundred requirements, "184 · 9 · 4 · 3" is arithmetic somebody has to do
 * before they know whether this delivery was mostly checked or mostly not — and the
 * whole point of the panel is that the absence of a finding is not a pass. One bar
 * answers that before it is read.
 *
 * Hand-drawn, like every other picture in this product: `sparkline.tsx` set the
 * precedent, and a charting library for four proportions would be a dependency, a
 * bundle and a theming problem in exchange for nothing.
 *
 * **It adds no information.** Every number in it is already in the badges beside it,
 * and it is `aria-hidden` with the counts left as text for a screen reader, because a
 * bar that has to be described in words is worse than the words.
 */

import type { CoverageState } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The order the segments sit in: best understood first, least understood last. */
export const SEGMENTS: CoverageState[] = ["checked", "traced_unchecked", "manual", "untraced"];

const TONE: Record<CoverageState, string> = {
  checked: "bg-success",
  traced_unchecked: "bg-warn",
  manual: "bg-info",
  untraced: "bg-destructive",
};

export function CoverageBar({
  counts,
  className,
}: {
  counts: Partial<Record<CoverageState, number>>;
  className?: string;
}) {
  const total = SEGMENTS.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
  if (total === 0) return null;

  return (
    <div
      className={cn("flex h-2.5 w-full overflow-hidden rounded-full bg-muted", className)}
      aria-hidden="true"
    >
      {SEGMENTS.map((state) => {
        const count = counts[state] ?? 0;
        if (count === 0) return null;
        return (
          <div
            key={state}
            className={TONE[state]}
            // A single requirement out of two hundred is a quarter of a pixel and
            // disappears. The floor keeps it visible, which matters most for the
            // segment that means "nothing checked this".
            style={{ width: `${Math.max((count / total) * 100, 1.5)}%` }}
          />
        );
      })}
    </div>
  );
}

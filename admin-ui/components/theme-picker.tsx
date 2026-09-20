"use client";

/**
 * Step through the palettes one at a time and stop on the one you want (Phase 6.6).
 *
 * Hidden when the administrator has locked the theme: the default then applies to
 * every browser, and a control that does nothing would only invite a support call.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { usePalette } from "@/components/palette-provider";
import { Button } from "@/components/ui/primitives";
import { PALETTE_LABELS } from "@/lib/theme";

export function PalettePicker() {
  const { palette, palettes, locked, step } = usePalette();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  // The server does not know the browser's choice, so the name is rendered only
  // after mount to keep the markup identical on both sides.
  if (locked || !mounted) return null;

  const position = palettes.indexOf(palette) + 1;
  return (
    <div className="inline-flex items-center gap-0.5" data-testid="palette-picker">
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        aria-label="Previous theme"
        onClick={() => step(-1)}
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </Button>
      <span
        className="min-w-[6.5rem] text-center text-[0.7rem]"
        title={`Theme ${position} of ${palettes.length}`}
      >
        {PALETTE_LABELS[palette]}
      </span>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        aria-label="Next theme"
        onClick={() => step(1)}
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

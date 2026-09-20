"use client";

/**
 * Which palette this browser shows, and whether the person may change it (ADR-031).
 *
 * The server renders `<html data-theme>` with the deployment's default so the first
 * paint is right. On mount the browser's own choice, where allowed, takes over; and
 * the appearance is re-read now and then so an administrator's change in the console
 * (a new default, or a lock) reaches open tabs without a redeploy.
 */

import * as React from "react";

import {
  PALETTES,
  PALETTE_STORAGE_KEY,
  nextPalette,
  parseAppearance,
  pickPalette,
  type Appearance,
  type Palette,
} from "@/lib/theme";

/** How often an open tab re-reads the appearance; the settings cache is five seconds. */
const REFRESH_MS = 60_000;

interface PaletteContextValue {
  palette: Palette;
  palettes: readonly Palette[];
  locked: boolean;
  setPalette: (palette: Palette) => void;
  step: (direction: 1 | -1) => void;
}

const PaletteContext = React.createContext<PaletteContextValue | null>(null);

function readStored(): Palette | null {
  try {
    const value = window.localStorage.getItem(PALETTE_STORAGE_KEY);
    return value ? pickPalette(value) : null;
  } catch {
    return null;
  }
}

function writeStored(palette: Palette | null) {
  try {
    if (palette === null) window.localStorage.removeItem(PALETTE_STORAGE_KEY);
    else window.localStorage.setItem(PALETTE_STORAGE_KEY, palette);
  } catch {
    // Storage may be unavailable; the choice then lasts for the tab.
  }
}

export function PaletteProvider({
  initial,
  children,
}: {
  initial: Appearance;
  children: React.ReactNode;
}) {
  const [appearance, setAppearance] = React.useState<Appearance>(initial);
  const [chosen, setChosen] = React.useState<Palette | null>(null);

  React.useEffect(() => setChosen(readStored()), []);

  React.useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const response = await fetch("/api/v1/appearance", { cache: "no-store" });
        if (!response.ok || cancelled) return;
        setAppearance(parseAppearance(await response.json(), initial.theme));
      } catch {
        // Keep what the server rendered with.
      }
    }
    const timer = window.setInterval(refresh, REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [initial.theme]);

  const palette = appearance.locked ? appearance.theme : (chosen ?? appearance.theme);

  React.useEffect(() => {
    document.documentElement.dataset.theme = palette;
  }, [palette]);

  const setPalette = React.useCallback(
    (next: Palette) => {
      if (appearance.locked) return;
      setChosen(next);
      writeStored(next);
    },
    [appearance.locked]
  );

  const value = React.useMemo<PaletteContextValue>(
    () => ({
      palette,
      palettes: PALETTES,
      locked: appearance.locked,
      setPalette,
      step: (direction) => setPalette(nextPalette(palette, direction)),
    }),
    [palette, appearance.locked, setPalette]
  );

  return <PaletteContext.Provider value={value}>{children}</PaletteContext.Provider>;
}

export function usePalette(): PaletteContextValue {
  const value = React.useContext(PaletteContext);
  if (!value) throw new Error("usePalette needs a PaletteProvider above it");
  return value;
}

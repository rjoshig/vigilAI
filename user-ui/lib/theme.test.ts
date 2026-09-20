import { describe, expect, it } from "vitest";

import {
  DEFAULT_PALETTE,
  PALETTES,
  PALETTE_LABELS,
  nextPalette,
  parseAppearance,
  pickPalette,
  type Palette,
} from "./theme";

describe("the palette from the environment", () => {
  it("accepts every known palette, whatever the casing or spacing", () => {
    for (const name of PALETTES) {
      expect(pickPalette(` ${name.toUpperCase()} `)).toBe(name);
    }
  });

  it("falls back to the brand palette for anything unknown or unset", () => {
    expect(DEFAULT_PALETTE).toBe("classic-teal-navy");
    expect(pickPalette(undefined)).toBe(DEFAULT_PALETTE);
    expect(pickPalette("")).toBe(DEFAULT_PALETTE);
    expect(pickPalette("neon")).toBe(DEFAULT_PALETTE);
  });
});

describe("stepping through the palettes", () => {
  it("visits every palette in order and wraps at both ends", () => {
    let current: Palette = PALETTES[0];
    const seen: Palette[] = [current];
    for (let i = 1; i < PALETTES.length; i += 1) {
      current = nextPalette(current, 1);
      seen.push(current);
    }
    expect(seen).toEqual([...PALETTES]);
    expect(nextPalette(current, 1)).toBe(PALETTES[0]);
    expect(nextPalette(PALETTES[0], -1)).toBe(PALETTES[PALETTES.length - 1]);
  });

  it("names every palette", () => {
    for (const name of PALETTES) expect(PALETTE_LABELS[name]).toBeTruthy();
  });
});

describe("the appearance answer", () => {
  it("reads the theme and the lock, falling back on anything odd", () => {
    expect(parseAppearance({ theme: "classic-teal", locked: true }, "default")).toEqual({
      theme: "classic-teal",
      locked: true,
    });
    expect(parseAppearance({ theme: "neon" }, "default")).toEqual({
      theme: "default",
      locked: false,
    });
    expect(parseAppearance(null, "classic-teal")).toEqual({ theme: "classic-teal", locked: false });
  });
});

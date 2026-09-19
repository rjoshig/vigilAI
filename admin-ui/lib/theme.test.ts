import { describe, expect, it } from "vitest";

import { DEFAULT_PALETTE, PALETTES, pickPalette } from "./theme";

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

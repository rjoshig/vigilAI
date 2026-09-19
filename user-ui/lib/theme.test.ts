import { describe, expect, it } from "vitest";

import { PALETTES, pickPalette } from "./theme";

describe("the palette from the environment", () => {
  it("accepts every known palette, whatever the casing or spacing", () => {
    for (const name of PALETTES) {
      expect(pickPalette(` ${name.toUpperCase()} `)).toBe(name);
    }
  });

  it("falls back to the default for anything unknown or unset", () => {
    expect(pickPalette(undefined)).toBe("default");
    expect(pickPalette("")).toBe("default");
    expect(pickPalette("neon")).toBe("default");
  });
});

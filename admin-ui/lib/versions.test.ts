import { describe, expect, it } from "vitest";

import { versionLabel } from "./versions";

describe("version labels", () => {
  it("reads the first save as v1.0 and counts up", () => {
    expect(versionLabel(1)).toBe("v1.0");
    expect(versionLabel(2)).toBe("v1.1");
    expect(versionLabel(12)).toBe("v1.11");
  });

  it("says when nothing has been saved yet", () => {
    expect(versionLabel(0)).toBe("unversioned");
    expect(versionLabel(Number.NaN)).toBe("unversioned");
  });
});

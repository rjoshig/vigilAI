import { describe, expect, it } from "vitest";

import { scopeKind, scopeLabel } from "@/components/scope-picker";
import type { Scope } from "@/lib/types";

const programmes = [
  { id: 1, code: "AS", label: "Account Solicitation", runs_using: 0 } as unknown as Scope,
];

describe("scope picker helpers", () => {
  it("classifies the three stored forms", () => {
    expect(scopeKind("all")).toBe("all");
    expect(scopeKind("programme:AS")).toBe("programme");
    expect(scopeKind("Acme Card Services")).toBe("customer");
  });

  it("reads a programme scope as the programme's name", () => {
    expect(scopeLabel("programme:AS", programmes)).toBe("Programme · Account Solicitation");
    expect(scopeLabel("programme:ZZ", programmes)).toBe("Programme · ZZ");
    expect(scopeLabel("all", null)).toBe("Everywhere");
    expect(scopeLabel("Acme", null)).toBe("Customer · Acme");
  });
});

import { describe, expect, it } from "vitest";

import {
  EVERYWHERE,
  parseScope,
  scopeIsComplete,
  scopeKind,
  scopeLabel,
  scopeToken,
} from "@/components/scope-picker";
import type { Scope } from "@/lib/types";

const programmes = [
  { id: 1, code: "AS", label: "Account Solicitation", runs_using: 0 } as unknown as Scope,
];

describe("scope picker helpers", () => {
  it("classifies every form that has ever been stored", () => {
    expect(scopeKind("")).toBe("all");
    expect(scopeKind("all")).toBe("all");
    expect(scopeKind(EVERYWHERE)).toBe("all");
    expect(scopeKind("programme:AS")).toBe("programme");
    expect(scopeKind("config:CFG-7")).toBe("configuration");
    expect(scopeKind("customer:Acme Card Services")).toBe("customer");
    expect(scopeKind("Acme Card Services")).toBe("customer");
  });

  it("renders the canonical token, whatever came in", () => {
    expect(scopeToken(parseScope("all"))).toBe("everywhere");
    expect(scopeToken(parseScope("Acme"))).toBe("customer:Acme");
    expect(scopeToken(parseScope("customer:Acme"))).toBe("customer:Acme");
    expect(scopeToken(parseScope("programme:AS"))).toBe("programme:AS");
    expect(scopeToken(parseScope("config:CFG-7"))).toBe("config:CFG-7");
  });

  it("reads a programme scope as the programme's name", () => {
    expect(scopeLabel("programme:AS", programmes)).toBe("Programme · Account Solicitation");
    expect(scopeLabel("programme:ZZ", programmes)).toBe("Programme · ZZ");
    expect(scopeLabel("all", null)).toBe("Everywhere");
    expect(scopeLabel("Acme", null)).toBe("Customer · Acme");
    expect(scopeLabel("customer:Acme", null)).toBe("Customer · Acme");
    expect(scopeLabel("config:CFG-7", null)).toBe("Configuration · CFG-7");
  });

  it("refuses a scope that names nothing", () => {
    expect(scopeIsComplete(EVERYWHERE)).toBe(true);
    expect(scopeIsComplete("customer:")).toBe(false);
    expect(scopeIsComplete("programme:")).toBe(false);
    expect(scopeIsComplete("customer:Acme")).toBe(true);
  });
});

import { describe, expect, it } from "vitest";

import { isOk, matrixStatus } from "@/lib/display";
import { buildMatrix, countByStatus, ruleValues } from "@/lib/matrix";
import type { ConfigElementOut, Finding, Requirements, Rule, Trace } from "@/lib/types";

function rule(overrides: Partial<Rule> = {}): Rule {
  return {
    rule_id: "R-001",
    source: "osl",
    req_type: "geography",
    summary: "geography — include ['AZ', 'IL']",
    confidence: 0.96,
    source_ref: "OSL section 3 Geography",
    source_text: "Include only consumers in Illinois or Arizona.",
    rule: { values: ["IL", "AZ"], mode: "include" },
    ...overrides,
  };
}

function trace(overrides: Partial<Trace> = {}): Trace {
  return {
    rule_id: "R-001",
    element_id: "C-003",
    verdict: "implemented",
    reason: "Same subject matter.",
    confidence: 0.9,
    by_code: false,
    ...overrides,
  };
}

function element(overrides: Partial<ConfigElementOut> = {}): ConfigElementOut {
  return {
    element_id: "C-003",
    json_path: "filters[0]",
    is_technical: false,
    description: "Keeps only records whose state is in the list.",
    rule: { values: ["IL", "AZ", "TX"] },
    ...overrides,
  };
}

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 1,
    finding_id: "F-01",
    type: "extra_rule_in_config",
    severity: "medium",
    title: "Config includes 1 value the OSL does not allow",
    detail: "In the config but not the OSL: TX.",
    leg: "osl_config",
    rule_ref: "R-001",
    element_ref: "C-003",
    evidence: {},
    rules_version: 1,
    review_status: "undecided",
    review_note: "",
    verified: false,
    verify_agreed: null,
    ...overrides,
  };
}

function requirements(overrides: Partial<Requirements> = {}): Requirements {
  return {
    rules: [rule()],
    traces: [trace()],
    elements: [element()],
    rules_version: 1,
    ...overrides,
  };
}

describe("buildMatrix", () => {
  it("joins a rule to its trace, element, and findings", () => {
    const rows = buildMatrix(requirements(), [finding()]);
    expect(rows).toHaveLength(1);
    expect(rows[0].rule.rule_id).toBe("R-001");
    expect(rows[0].element?.json_path).toBe("filters[0]");
    expect(rows[0].findings).toHaveLength(1);
  });

  it("marks a traced requirement with no findings as a match", () => {
    expect(buildMatrix(requirements(), [])[0].status).toBe("match");
  });

  it("marks an untraced requirement as missing", () => {
    const rows = buildMatrix(
      requirements({ traces: [trace({ element_id: null, verdict: "not_related" })] }),
      []
    );
    expect(rows[0].status).toBe("missing");
    expect(rows[0].element).toBeNull();
  });

  it("marks a requirement with no trace at all as missing", () => {
    expect(buildMatrix(requirements({ traces: [] }), [])[0].status).toBe("missing");
  });

  it("marks a value mismatch as a mismatch", () => {
    const rows = buildMatrix(requirements(), [finding({ type: "value_mismatch" })]);
    expect(rows[0].status).toBe("mismatch");
  });

  it("marks an extra config value as extra", () => {
    expect(buildMatrix(requirements(), [finding()])[0].status).toBe("extra");
  });

  it("marks a partial verdict as partial", () => {
    const rows = buildMatrix(requirements({ traces: [trace({ verdict: "partial" })] }), []);
    expect(rows[0].status).toBe("partial");
  });

  it("marks a contradicting element as a mismatch", () => {
    const rows = buildMatrix(requirements({ traces: [trace({ verdict: "contradicts" })] }), []);
    expect(rows[0].status).toBe("mismatch");
  });

  it("ignores findings that belong to another requirement", () => {
    const rows = buildMatrix(requirements(), [finding({ rule_ref: "R-999" })]);
    expect(rows[0].findings).toHaveLength(0);
    expect(rows[0].status).toBe("match");
  });

  it("ignores findings with no requirement at all", () => {
    const rows = buildMatrix(requirements(), [finding({ rule_ref: "" })]);
    expect(rows[0].findings).toHaveLength(0);
  });

  it("keeps the order the rules arrived in", () => {
    const rows = buildMatrix(
      requirements({
        rules: [rule({ rule_id: "R-002" }), rule({ rule_id: "R-001" })],
        traces: [],
      }),
      []
    );
    expect(rows.map((r) => r.rule.rule_id)).toEqual(["R-002", "R-001"]);
  });
});

describe("countByStatus", () => {
  it("counts every status, including the empty ones", () => {
    const counts = countByStatus(buildMatrix(requirements(), [finding()]));
    expect(counts.extra).toBe(1);
    expect(counts.match).toBe(0);
  });
});

describe("ruleValues", () => {
  it("renders a set requirement as its members", () => {
    expect(ruleValues(rule())).toBe("IL, AZ");
  });

  it("renders a criteria requirement as its conditions", () => {
    const criteria = rule({
      req_type: "criteria",
      rule: { conditions: [{ field_name: "score", operator: ">=", value: 755 }] },
    });
    expect(ruleValues(criteria)).toBe("score >= 755");
  });

  it("joins multiple conditions with AND", () => {
    const criteria = rule({
      req_type: "criteria",
      rule: {
        conditions: [
          { field_name: "score", operator: ">=", value: 755 },
          { field_name: "age", operator: ">=", value: 21 },
        ],
      },
    });
    expect(ruleValues(criteria)).toBe("score >= 755 AND age >= 21");
  });

  it("renders a waterfall as its ordered steps", () => {
    const waterfall = rule({ req_type: "waterfall", rule: { steps: ["geo", "score"] } });
    expect(ruleValues(waterfall)).toBe("geo → score");
  });

  it("renders a quantity as its number", () => {
    expect(ruleValues(rule({ req_type: "quantity", rule: { quantity: 50000 } }))).toBe("50000");
  });

  it("falls back to an em dash when there is nothing to show", () => {
    expect(ruleValues(rule({ rule: {} }))).toBe("—");
  });
});

describe("matrixStatus", () => {
  it("treats a null trace as missing", () => {
    expect(matrixStatus(null, [])).toBe("missing");
  });

  it("treats a report violation as a mismatch", () => {
    expect(matrixStatus(trace(), ["report_violates_rule"])).toBe("mismatch");
  });

  it("treats an unrecognised finding type as partial, not a match", () => {
    expect(matrixStatus(trace(), ["profile_anomaly"])).toBe("partial");
  });
});

describe("isOk", () => {
  it("reads a confirmed finding as Not OK for the delivery", () => {
    expect(isOk("confirmed")).toBe(false);
  });

  it("reads a false positive and an accepted risk as OK", () => {
    expect(isOk("false_positive")).toBe(true);
    expect(isOk("accepted_risk")).toBe(true);
  });

  it("reads an undecided finding as not OK yet", () => {
    expect(isOk("undecided")).toBe(false);
  });
});

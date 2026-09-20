import { describe, expect, it } from "vitest";

import { REVIEW_LABEL, decisionProblem, isOk } from "./display";

describe("isOk", () => {
  it("reads the two OK statuses as OK and 'confirmed' as Not OK", () => {
    expect(isOk("false_positive")).toBe(true);
    expect(isOk("accepted_risk")).toBe(true);
    expect(isOk("confirmed")).toBe(false);
    expect(isOk("undecided")).toBe(false);
  });

  it("labels every status the way the reviewer chose it", () => {
    expect(REVIEW_LABEL.confirmed).toBe("Not OK");
    expect(REVIEW_LABEL.false_positive).toContain("OK");
    expect(REVIEW_LABEL.accepted_risk).toContain("OK");
  });
});

describe("decisionProblem", () => {
  it("wants a reason for an accepted risk at any severity", () => {
    expect(decisionProblem("low", "accepted_risk", "")).not.toBe("");
    expect(decisionProblem("high", "accepted_risk", "")).not.toBe("");
    expect(decisionProblem("low", "accepted_risk", "signed off last quarter")).toBe("");
  });

  it("wants a comment for Not OK on a serious or uncertain finding", () => {
    expect(decisionProblem("high", "confirmed", "")).not.toBe("");
    expect(decisionProblem("review", "confirmed", "")).not.toBe("");
    expect(decisionProblem("high", "confirmed", "threshold is wrong")).toBe("");
  });

  it("asks nothing of a low finding or of a false positive", () => {
    expect(decisionProblem("low", "confirmed", "")).toBe("");
    expect(decisionProblem("medium", "confirmed", "")).toBe("");
    expect(decisionProblem("high", "false_positive", "")).toBe("");
  });

  it("treats whitespace as no comment at all", () => {
    expect(decisionProblem("high", "confirmed", "   ")).not.toBe("");
  });
});

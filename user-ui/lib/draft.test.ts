import { describe, expect, it } from "vitest";

import { attachedByKind, draftToForm, expiresIn } from "@/lib/draft";
import type { RunDetail } from "@/lib/types";

function makeDraft(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 7,
    customer_name: "Northwind",
    order_number: "ORD-10001",
    configuration_id: "CFG-01",
    status: "draft",
    current_stage: "",
    error: "",
    created_at: "2026-09-21T10:00:00Z",
    finished_at: null,
    submitted_by: "John Doe",
    scope: "AM",
    scope_label: "Account Monitoring",
    high: 0,
    medium: 0,
    low: 0,
    review: 0,
    queue_position: null,
    credit_date: "2026-03-31",
    error_detail: "",
    notes: "check the exclusions",
    rules_version: 1,
    model_used: "",
    prompt_version: "",
    summary: "",
    top_issues: [],
    rerun_reason: "",
    input_fingerprint: "",
    config_notes: [],
    can_finalize: false,
    finalize_blocked_by: "",
    finalized: false,
    pdf_available: false,
    stages: [],
    files: {},
    mismatches: [],
    ...overrides,
  } as RunDetail;
}

describe("draftToForm", () => {
  it("carries every field the submitter typed", () => {
    const form = draftToForm(makeDraft({ has_suppressions: true, delivery_notes: "two parts" }));
    expect(form.customer).toBe("Northwind");
    expect(form.order).toBe("ORD-10001");
    expect(form.configurationId).toBe("CFG-01");
    expect(form.creditDate).toBe("2026-03-31");
    expect(form.notes).toBe("check the exclusions");
    expect(form.scope).toBe("AM");
    expect(form.hasSuppressions).toBe(true);
    expect(form.deliveryNotes).toBe("two parts");
  });

  it("never hands back null, because the inputs are controlled", () => {
    // A null credit date would turn a controlled input into an uncontrolled one the
    // first time somebody typed in it, which React warns about and then misbehaves.
    const form = draftToForm(makeDraft({ credit_date: null }));
    expect(form.creditDate).toBe("");
    expect(form.hasSuppressions).toBe(false);
  });
});

describe("attachedByKind", () => {
  it("groups parts under their kind and prefers the label", () => {
    const run = makeDraft({
      files_detail: [
        { id: 1, kind: "dirt", part: 1, part_label: "", filename: "dirt.xlsx", size_bytes: 10 },
        {
          id: 2,
          kind: "field_distribution",
          part: 1,
          part_label: "segment A",
          filename: "fd1.xlsx",
          size_bytes: 10,
        },
        {
          id: 3,
          kind: "field_distribution",
          part: 2,
          part_label: "segment B",
          filename: "fd2.xlsx",
          size_bytes: 10,
        },
      ],
    });
    expect(attachedByKind(run)).toEqual({
      dirt: ["dirt.xlsx"],
      field_distribution: ["segment A", "segment B"],
    });
  });

  it("is empty for a draft with nothing uploaded", () => {
    expect(attachedByKind(makeDraft())).toEqual({});
  });
});

describe("expiresIn", () => {
  const now = new Date("2026-09-21T12:00:00Z");

  it("counts whole days", () => {
    expect(expiresIn("2026-09-24T12:00:00Z", now)).toBe("expires in 3 days");
    expect(expiresIn("2026-09-22T12:00:00Z", now)).toBe("expires in 1 day");
  });

  it("falls back to hours, then to today", () => {
    expect(expiresIn("2026-09-21T15:00:00Z", now)).toBe("expires in 3 hours");
    // Never "expires in 0 days": a draft with minutes left should read as urgent.
    expect(expiresIn("2026-09-21T12:30:00Z", now)).toBe("expires today");
  });

  it("says so when the window has passed", () => {
    expect(expiresIn("2026-09-20T12:00:00Z", now)).toBe("expired");
  });

  it("says nothing when there is no expiry", () => {
    expect(expiresIn(null, now)).toBe("");
    expect(expiresIn("not-a-date", now)).toBe("");
  });
});

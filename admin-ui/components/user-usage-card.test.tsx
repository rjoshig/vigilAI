/**
 * The spreadsheet an administrator downloads from the usage screen (Phase 6.19).
 *
 * The file leaves the product and turns up in a report somebody else reads, so the
 * failure that matters is the quiet one: a name with a comma in it splitting a row, or
 * a download that holds the page on screen rather than the period asked for.
 */

import { describe, expect, it } from "vitest";

import { csvFilename, toCsv } from "./user-usage-card";
import type { UsageByUser, UserUsage } from "@/lib/types";

function person(overrides: Partial<UserUsage> = {}): UserUsage {
  return {
    user_id: 1,
    name: "Jo Bloggs",
    username: "jo",
    roles: ["user"],
    is_active: true,
    runs: 4,
    finalized: 2,
    needs_review: 1,
    failed: 1,
    held: 0,
    cancelled: 0,
    in_flight: 0,
    orders: 3,
    customers: 2,
    configurations: 2,
    repeat_runs: 1,
    mismatch_runs: 0,
    high_findings: 5,
    completed_runs: 3,
    failure_rate: 0.25,
    held_rate: 0,
    repeat_rate: 0.25,
    high_per_run: 1.67,
    first_run_at: "2026-09-01T09:00:00Z",
    last_run_at: "2026-09-19T17:00:00Z",
    per_day: [],
    ...overrides,
  };
}

function period(users: UserUsage[]): UsageByUser {
  return {
    start: "2026-08-23",
    end: "2026-09-21",
    days: 30,
    users,
    runs: users.reduce((total, row) => total + row.runs, 0),
    failure_rate: 0.1,
    held_rate: 0.05,
    repeat_rate: 0.2,
    periods: [7, 30, 90, 180],
  };
}

describe("the usage spreadsheet", () => {
  it("carries a header in words rather than field names", () => {
    const [header] = toCsv(period([person()])).split("\n");

    expect(header).toContain("Person");
    expect(header).toContain("Failed");
    expect(header).toContain("High findings per completed run");
    expect(header).not.toContain("user_id");
  });

  it("holds every person in the period, not the page on screen", () => {
    const many = Array.from({ length: 23 }, (_, index) =>
      person({ user_id: index + 1, name: `Person ${index + 1}` })
    );

    const rows = toCsv(period(many)).split("\n");

    // A header, 23 people, a blank line and the averages.
    expect(rows).toHaveLength(26);
    expect(rows[23]).toContain("Person 23");
  });

  it("quotes a name containing a comma rather than splitting the row", () => {
    const csv = toCsv(period([person({ name: "Bloggs, Jo" })]));
    const row = csv.split("\n")[1];

    expect(row.startsWith('"Bloggs, Jo",')).toBe(true);
  });

  it("doubles a quote inside a value, which is what a reader expects", () => {
    const csv = toCsv(period([person({ name: 'Jo "The Closer" Bloggs' })]));

    expect(csv).toContain('"Jo ""The Closer"" Bloggs"');
  });

  it("ends with the averages a rate is read against", () => {
    const rows = toCsv(period([person()])).split("\n");

    expect(rows[rows.length - 1]).toContain("Across everybody");
    expect(rows[rows.length - 1]).toContain("failure rate 0.1");
  });

  it("names the file after the period, so a folder of them sorts", () => {
    expect(csvFilename(period([person()]))).toBe("usage-by-person-2026-08-23-to-2026-09-21.csv");
  });
});

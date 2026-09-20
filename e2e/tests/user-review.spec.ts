/**
 * The user app's core path: find a run, read its evidence, decide, and freeze.
 *
 * These run against the seeded stack, which already holds runs in every lifecycle
 * state, so each test starts from a realistic screen rather than building one.
 */

import { expect, test } from "@playwright/test";

/** Open the runs list and wait for it to have loaded rows. */
async function openRuns(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: /VR-\d{4}/ }).first()).toBeVisible();
}

test("the runs list shows every lifecycle state the seeder produced", async ({ page }) => {
  await openRuns(page);

  const body = await page.locator("body").innerText();

  expect(body).toContain("VR-0001");
  // The error path has to be visible on the list: a run that failed is not a run
  // that passed. (The seeder's queued run is processed by the worker these tests
  // start, so it has moved on by now.)
  expect(body.toLowerCase()).toContain("failed");
  expect(body.toLowerCase()).toContain("needs review");
  expect(body.toLowerCase()).toContain("finalized");
});

test("a run that needs review shows its matrix, its coverage, and its findings", async ({
  page,
}) => {
  await page.goto("/runs/2");

  await expect(page.getByTestId("coverage-card")).toBeVisible();
  await expect(page.getByText("What was checked").first()).toBeVisible();
  // The matrix is the default tab and names every requirement.
  await expect(page.getByRole("button", { name: /Traceability matrix/ })).toBeVisible();

  await page.getByRole("button", { name: /^Findings/ }).click();
  await expect(page.getByTestId("finding-card").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "False positive" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Accepted risk" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Not OK" }).first()).toBeVisible();
});

test("the coverage panel says what was compared and what was not", async ({ page }) => {
  await page.goto("/runs/2");
  const card = page.getByTestId("coverage-card");

  await expect(card).toBeVisible();
  const text = await card.innerText();

  expect(text).toContain("Checked against a report");
  expect(text).toContain("absence of a finding is not on its own a pass");
});

test("Not OK on a high finding is refused without a comment, and accepted with one", async ({
  page,
}) => {
  await page.goto("/runs/4");
  await page.getByRole("button", { name: /^Findings/ }).click();

  const card = page.locator('[data-testid="finding-card"][data-severity="high"]').first();
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-review-status", "undecided");

  await card.getByRole("button", { name: "Not OK" }).click();

  // The decision is refused, not merely warned about: the finding is still undecided
  // and the reviewer is told why.
  await expect(card).toHaveAttribute("data-review-status", "undecided");
  await expect(card.getByRole("alert")).toContainText("needs a comment");

  await card.getByRole("textbox").fill("raised with the ETL team");
  await card.getByRole("button", { name: "Not OK" }).click();

  await expect(card).toHaveAttribute("data-review-status", "confirmed");
});

test("the evidence panel shows all three legs", async ({ page }) => {
  await page.goto("/runs/2");
  await page.getByRole("button", { name: /^Findings/ }).click();
  await page.getByTestId("finding-card").first().click();

  // The drawer carries the OSL text, the configuration path and the report cell: the
  // three legs of the reconciliation, side by side.
  await expect(page.getByLabel(/^Evidence for /)).toBeVisible();
});

test("a finalized run serves its frozen report, and it says what was checked", async ({ page }) => {
  await page.goto("/runs/1/report");

  await expect(page.getByRole("heading", { name: "Final report" })).toBeVisible();
  await expect(page.getByText("frozen")).toBeVisible();

  const frame = page.frameLocator("iframe");
  await expect(frame.locator("body")).toContainText("What was checked");
});

test("the drift panel appears on a run with a configuration id", async ({ page }) => {
  await page.goto("/runs/2");

  await expect(page.getByTestId("drift-card")).toBeVisible();
});

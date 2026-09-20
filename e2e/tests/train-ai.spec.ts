/**
 * Train AI mode, from the reviewer's side (Phase 6.13b).
 *
 * The seeded stack has the mode on. These tests record an observation from each of the
 * places a reviewer forms an opinion — a finding card, the evidence drawer, a coverage
 * gap — and then find it on My observations with an honest status. A second Save on the
 * same form is an update, not a duplicate.
 */

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

/** A run the seeder leaves at "needs review", with findings and coverage gaps. */
const RUN = 2;

async function countMine(page: Page): Promise<number> {
  const reply = await page.request.get(`/api/v1/observations?mine=true&at=${Date.now()}`);
  expect(reply.ok()).toBeTruthy();
  return ((await reply.json()) as unknown[]).length;
}

async function fillAndSave(page: Page, statement: string): Promise<void> {
  const dialog = page.getByRole("dialog", { name: /What should this check|Your observation/ });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(/What should the tool check/).fill(statement);
  await dialog.getByRole("button", { name: /^Save observation$/ }).click();
  await expect(dialog.getByTestId("observation-saved")).toBeVisible();
}

test("an observation from a finding card lands on My observations as waiting", async ({ page }) => {
  const before = await countMine(page);
  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  const card = page.getByTestId("finding-card").first();
  await expect(card).toBeVisible();

  await card.getByRole("button", { name: /What should this check/ }).click();
  await fillAndSave(page, "The state column should only ever hold the two states in scope.");

  expect(await countMine(page)).toBe(before + 1);
  await page.goto("/observations");
  await expect(page.getByTestId("outcome").first()).toHaveText("Waiting");
  await expect(page.getByText("two states in scope").first()).toBeVisible();
});

test("a second Save on the same form rewords the observation rather than duplicating it", async ({
  page,
}) => {
  const before = await countMine(page);
  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  await page
    .getByTestId("finding-card")
    .first()
    .getByRole("button", { name: /What should this check/ })
    .click();
  await fillAndSave(page, "First wording of a thought about this finding.");

  const dialog = page.getByRole("dialog", { name: /Your observation/ });
  await dialog.getByLabel(/What should the tool check/).fill("Second, better wording.");
  await dialog.getByRole("button", { name: /^Save changes$/ }).click();
  await expect(dialog.getByTestId("observation-saved")).toBeVisible();

  expect(await countMine(page)).toBe(before + 1);
  const mine = (await (
    await page.request.get(`/api/v1/observations?mine=true&at=${Date.now()}`)
  ).json()) as Array<{ statement: string }>;
  expect(mine.some((row) => row.statement === "Second, better wording.")).toBe(true);
  expect(mine.some((row) => row.statement.startsWith("First wording"))).toBe(false);
});

test("the evidence drawer offers the button where the opinion forms", async ({ page }) => {
  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  await page.getByTestId("finding-card").first().click();

  const drawer = page.getByRole("dialog", { name: /Evidence for/ });
  await expect(drawer).toBeVisible();
  await drawer.getByTestId("drawer-observe").click();

  await expect(page.getByRole("dialog", { name: /What should this check/ })).toBeVisible();
  await expect(page.getByTestId("anchor-chip").first()).toBeVisible();
});

test("a coverage gap can say what should have been checked", async ({ page }) => {
  await page.goto(`/runs/${RUN}`);
  const card = page.getByTestId("coverage-card");
  await expect(card).toBeVisible();
  const show = card.getByRole("button", { name: /Show the \d+ that nothing evidenced/ });
  test.skip((await show.count()) === 0, "this run has no coverage gap to point at");

  await show.click();
  await card.getByTestId("gap-observe").first().click();

  const dialog = page.getByRole("dialog", { name: /What should this check/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/nothing checked it/)).toBeVisible();
});

test("the rules applied to a run are listed by origin", async ({ page }) => {
  await page.goto(`/runs/${RUN}`);
  const reply = await page.request.get(`/api/v1/runs/${RUN}/rules`);
  expect(reply.ok()).toBeTruthy();
  const rules = (await reply.json()) as { applied: unknown[]; running_silently: unknown[] };
  test.skip(
    rules.applied.length === 0 && rules.running_silently.length === 0,
    "no admin or learned rule touched this run"
  );

  const panel = page.getByTestId("rules-applied");
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: /Rules applied to this run/ }).click();
  await expect(panel.getByText(/finding/).first()).toBeVisible();
});

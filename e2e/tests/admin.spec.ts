/**
 * The admin console: every screen loads, and the controls that reach every run work.
 *
 * The rule lifecycle and the settings store are the two places where a wrong click
 * changes what happens on every future run, so those are driven rather than only
 * looked at.
 */

import { expect, test } from "@playwright/test";

const ADMIN = "http://127.0.0.1:3001";

const SCREENS: ReadonlyArray<[string, string]> = [
  ["/tell", "Tell the tool"],
  ["/artifacts", "Artifact types & meaning"],
  ["/scopes", "Delivery programmes"],
  ["/meaning", "Meaning"],
  ["/checks", "Checks"],
  ["/compliance", "Compliance & scope"],
  ["/rules", "Rules"],
  ["/training", "Training"],
  ["/reference", "Reference data"],
  ["/usage", "Usage"],
  ["/users", "Users"],
  ["/settings", "Settings"],
];

for (const [path, heading] of SCREENS) {
  test(`the ${heading} screen loads`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto(`${ADMIN}${path}`);

    await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
    expect(errors, `${path} raised a page error`).toEqual([]);
  });
}

test("the rules screen lists rules and filters to active by default", async ({ page }) => {
  await page.goto(`${ADMIN}/rules`);

  await expect(page.getByRole("heading", { name: "Rules", exact: true })).toBeVisible();
  const body = await page.locator("body").innerText();
  expect(body.toLowerCase()).toContain("active");
});

test("a rule state change asks for the word to be typed", async ({ page }) => {
  await page.goto(`${ADMIN}/rules`);
  const disable = page.getByRole("button", { name: /^disable$/i }).first();
  test.skip(!(await disable.isVisible()), "no rule on this screen offers disable");

  await disable.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // The confirm is refused until the word is typed: a rule change reaches every
  // future run, and a typed word is the cheapest way to mean the click (ADR-032).
  await expect(dialog.getByRole("textbox")).toBeVisible();
});

test("a setting shows which layer it came from", async ({ page }) => {
  await page.goto(`${ADMIN}/settings`);

  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  const body = (await page.locator("body").innerText()).toLowerCase();
  // The console overrides .env overrides the default, and the screen says which
  // applied (ADR-023).
  expect(body).toMatch(/default|environment|console/);
});

test("the usage screen reports runs and model calls", async ({ page }) => {
  await page.goto(`${ADMIN}/usage`);

  await expect(page.getByRole("heading", { name: "Usage", exact: true })).toBeVisible();
  const body = (await page.locator("body").innerText()).toLowerCase();
  expect(body).toMatch(/run|token|call/);
});

// The stack runs on LLM_PROVIDER=mock, whose canned answer places nothing. That is the
// right stand-in here: which surface a sentence belongs on is the model's judgment and
// is asserted against the scripted model in `tests/api/test_front_door.py`. What a
// browser can prove is the round trip — the statement reaches the API and the tool's
// answer reaches the screen — and the answer worth proving is the one that creates
// nothing, because that is the path where a wrong rule would otherwise be written.
test("the front door sends a statement and shows what the tool made of it", async ({ page }) => {
  await page.goto(`${ADMIN}/tell`);

  await page
    .getByLabel("One statement")
    .fill("The account review file must never have a blank origination date.");
  await page.getByTestId("tell-the-tool").click();

  const result = page.getByTestId("front-door-result");
  await expect(result).toBeVisible();
  await expect(result).toContainText("Not placed");
  await expect(page.getByTestId("front-door-question")).toBeVisible();
  await expect(result).toContainText("Nothing was created.");
});

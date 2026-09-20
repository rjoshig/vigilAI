/**
 * Theme and viewport: the things that look fine on a developer's screen and break on
 * somebody else's.
 */

import { expect, test } from "@playwright/test";

test("the four palettes each apply without a page error", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();

  for (const theme of ["default", "slate", "forest", "plum"]) {
    await page.evaluate((name) => {
      document.documentElement.dataset.theme = name;
    }, theme);
    // Whatever the palette, text has to remain on a background it contrasts with.
    await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();
  }

  expect(errors).toEqual([]);
});

test("the runs screen is usable at phone width with no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs");

  await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow, "the page scrolls sideways at phone width").toBeLessThanOrEqual(1);
});

test("the review screen is usable at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/2");

  await expect(page.getByTestId("coverage-card")).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
});

test("the admin console opens from the user app", async ({ page }) => {
  await page.goto("/runs");

  const launcher = page.getByRole("link", { name: /Admin console/i });
  await expect(launcher).toBeVisible();
  await expect(launcher).toHaveAttribute("href", /3001/);
});

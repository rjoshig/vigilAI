/**
 * The fail-closed gate, end to end in a browser (ADR-035).
 *
 * This is the path a compliance error would take to escape: decide the findings, see
 * nothing else, freeze. The test drives the whole of it, including the acknowledgement
 * the gate now wants and the confirmation the reviewer has to read.
 *
 * It is one test rather than four because freezing a run is one-way: a suite of small
 * tests over the same run would depend on each other's order and fail for reasons that
 * have nothing to do with the gate. It owns run 5 alone.
 */

import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

const RUN = 5;

/**
 * Decide every finding on the review screen.
 *
 * It takes the first still-undecided card each time rather than counting once and
 * indexing: the list is fetched after the tab renders, so a count taken too early
 * misses findings, and each decision re-renders the list.
 */
async function decideEveryFinding(page: Page): Promise<void> {
  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  await expect(page.getByTestId("finding-card").first()).toBeVisible();

  // Read the ids once. Deciding a finding re-renders the list, and both "the first
  // undecided card" and a count taken at the wrong moment are moving targets: during a
  // refetch the list is briefly empty, which would look like nothing left to do.
  const ids = await page.$$eval('[data-testid="finding-card"]', (cards) =>
    cards.map((card) => card.getAttribute("data-finding") ?? "")
  );
  expect(ids.length, "the run should have findings to decide").toBeGreaterThan(0);

  for (const id of ids) {
    const card = page.locator(`[data-testid="finding-card"][data-finding="${id}"]`);
    await expect(card).toBeVisible();
    await card.getByRole("textbox").fill("checked by hand");
    await card.getByRole("button", { name: "False positive" }).click();
    // Clicking only starts the request; the attribute changing is it landing.
    await expect(card).toHaveAttribute("data-review-status", "false_positive");
  }

  await expect(
    page.locator('[data-testid="finding-card"][data-review-status="undecided"]')
  ).toHaveCount(0);
}

/** How many coverage gaps are still waiting for someone to say they saw them. */
async function outstandingCount(card: Locator): Promise<number> {
  const badge = card.getByText(/\d+ to acknowledge/);
  if ((await badge.count()) === 0) return 0;
  const text = await badge.first().innerText();
  return Number(text.match(/\d+/)?.[0] ?? 0);
}

test("a run is frozen only once every finding is decided and every gap acknowledged", async ({
  page,
}) => {
  await decideEveryFinding(page);

  await page.goto(`/runs/${RUN}/report`);
  const generate = page.getByRole("button", { name: /Generate final report/ });
  const coverage = page.getByTestId("coverage-card");
  await expect(coverage).toBeVisible();

  // Deciding the findings is not enough while a gap is outstanding.
  if ((await outstandingCount(coverage)) > 0) {
    await expect(generate).toBeDisabled();
    await expect(page.getByText(/Not yet:/)).toBeVisible();

    await coverage.getByLabel("Acknowledgement note").fill("raised with the delivery lead");
    await coverage.getByRole("button", { name: /I have seen all/ }).click();
    await expect(coverage.getByText("nothing outstanding")).toBeVisible();
  }

  // The report screen reads the run once, when it mounts. Reload until it agrees with
  // the server rather than asserting the screen live-updates, which it does not claim
  // to do.
  await expect
    .poll(
      async () => {
        if (await generate.isEnabled()) return true;
        await page.reload();
        await expect(generate).toBeVisible();
        return generate.isEnabled();
      },
      { timeout: 30_000, message: "the gate never opened after everything was done" }
    )
    .toBe(true);

  // Freezing asks once, and says what it is freezing.
  await generate.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("never regenerated");
  await expect(dialog).toContainText("requirements");
  await dialog.getByRole("button", { name: /Yes, generate it/ }).click();

  // Reload rather than assert the screen live-updates: it reads the run when it
  // mounts, and what matters is that the run is frozen and stays frozen.
  await expect(dialog).toHaveCount(0, { timeout: 30_000 });
  await page.reload();

  await expect(page.getByText("frozen")).toBeVisible({ timeout: 30_000 });
  await expect(generate).toHaveCount(0);

  // And the frozen report states the limits of what was verified.
  const frame = page.frameLocator("iframe");
  await expect(frame.locator("body")).toContainText("What was checked");
});

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

/** Read the current findings from the server, never from a response read earlier. */
async function storedFindings(
  page: Page
): Promise<Array<{ finding_id: string; shadow?: boolean; review_status: string }>> {
  // A cache-busting parameter, because every read here exists to find out what changed
  // and a replayed body is the one answer that cannot. FastAPI ignores the extra key.
  const reply = await page.request.get(`/api/v1/runs/${RUN}/findings?at=${Date.now()}`);
  expect(reply.ok(), "the findings should be readable").toBeTruthy();
  return reply.json();
}

/** Which findings a reviewer still has to decide, according to the server. */
async function undecidedIds(page: Page): Promise<string[]> {
  return (await storedFindings(page))
    .filter((f) => !f.shadow && f.review_status === "undecided")
    .map((f) => f.finding_id);
}

/**
 * Decide every finding on the review screen.
 *
 * Each pass asks the server which findings are still undecided and drives exactly
 * those. Reading that from the cards instead would let one stale render skip a finding
 * permanently: the loop would see a decision the browser believes it made, the gate
 * would read what the server actually stored, and the two disagreeing is the whole
 * reason this reads the server between passes.
 */
async function decideEveryFinding(page: Page): Promise<void> {
  const expected = (await storedFindings(page)).filter((f) => !f.shadow).length;
  expect(expected, "the run should have findings to decide").toBeGreaterThan(0);

  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  await expect(page.getByTestId("finding-card")).toHaveCount(expected);

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const left = await undecidedIds(page);
    if (left.length === 0) return;

    for (const id of left) {
      const card = page.locator(`[data-testid="finding-card"][data-finding="${id}"]`);
      await expect(card).toBeVisible();
      await card.getByRole("textbox").fill("checked by hand");
      await card.getByRole("button", { name: "False positive" }).click();
      await expect(card).toHaveAttribute("data-review-status", "false_positive");
    }

    if ((await undecidedIds(page)).length === 0) return;
    await page.reload();
    await page.getByRole("button", { name: /^Findings/ }).click();
    await expect(page.getByTestId("finding-card")).toHaveCount(expected);
  }
  throw new Error("some findings stayed undecided after three passes");
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

  // The server has not frozen anything yet, so say so before reading the screen: if the
  // page disagrees, what failed is the reading and not the gate, and the two are worth
  // telling apart.
  const before = await page.request.get(`/api/v1/runs/${RUN}?at=${Date.now()}`);
  expect((await before.json()).finalized, "the run should not be frozen yet").toBe(false);

  const generate = page.getByRole("button", { name: /Generate final report/ });
  const coverage = page.getByTestId("coverage-card");

  await page.goto(`/runs/${RUN}/report`);
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

  // Wait for the request itself rather than for the screen to catch up: a freeze that
  // never reached the server is the failure worth reporting precisely. The outcome
  // asserted is that the run ends up frozen, not the status of one reply — a second
  // identical request is refused by design, and that refusal is not a failure here
  // (ADR-005).
  await Promise.all([
    page.waitForResponse(
      (reply) =>
        reply.url().includes(`/runs/${RUN}/finalize`) && reply.request().method() === "POST"
    ),
    dialog.getByRole("button", { name: /Yes, generate it/ }).click(),
  ]);

  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/v1/runs/${RUN}?at=${Date.now()}`)).json()).finalized,
      {
        timeout: 30_000,
        message: "the run never became frozen after the confirmation",
      }
    )
    .toBe(true);

  // Reload rather than assert the screen live-updates: it reads the run when it mounts,
  // and what matters is that the run is frozen and stays frozen. The badge appears once
  // that read returns, so wait for it rather than for the reload to resolve.
  await page.reload();
  await expect(page.getByText("frozen").first()).toBeVisible({ timeout: 30_000 });
  await expect(generate).toHaveCount(0);

  // And the frozen report states the limits of what was verified. Read it from the
  // server rather than through the iframe, which the browser may still be showing
  // from before the freeze.
  const report = await page.request.get(`/api/v1/runs/${RUN}/report`);
  expect(report.status()).toBe(200);
  expect(await report.text()).toContain("What was checked");
});

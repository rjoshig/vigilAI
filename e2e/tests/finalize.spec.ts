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
  // Ask the API how many findings there are before reading the screen. The list
  // renders progressively, so a count taken from the DOM at the wrong moment misses
  // one, and a missed finding leaves the gate shut for a reason the test cannot see.
  const findings = await (await page.request.get(`/api/v1/runs/${RUN}/findings`)).json();
  const expected = findings.filter((f: { shadow?: boolean }) => !f.shadow).length;
  expect(expected, "the run should have findings to decide").toBeGreaterThan(0);

  await page.goto(`/runs/${RUN}`);
  await page.getByRole("button", { name: /^Findings/ }).click();
  await expect(page.getByTestId("finding-card")).toHaveCount(expected);

  // Read the ids once. Deciding a finding re-renders the list, and both "the first
  // undecided card" and a count taken at the wrong moment are moving targets: during a
  // refetch the list is briefly empty, which would look like nothing left to do.
  const ids = await page.$$eval('[data-testid="finding-card"]', (cards) =>
    cards.map((card) => card.getAttribute("data-finding") ?? "")
  );
  expect(ids).toHaveLength(expected);

  // Decide each one, then check against the server rather than the screen. A decision
  // the card shows is a decision the browser believes it made; what the gate reads is
  // what the server stored, and the two can differ while a request is in flight.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    for (const id of ids) {
      const card = page.locator(`[data-testid="finding-card"][data-finding="${id}"]`);
      await expect(card).toBeVisible();
      if ((await card.getAttribute("data-review-status")) !== "undecided") continue;
      await card.getByRole("textbox").fill("checked by hand");
      await card.getByRole("button", { name: "False positive" }).click();
      await expect(card).toHaveAttribute("data-review-status", "false_positive");
    }

    const stored = await (await page.request.get(`/api/v1/runs/${RUN}/findings`)).json();
    const left = stored.filter(
      (f: { shadow?: boolean; review_status: string }) =>
        !f.shadow && f.review_status === "undecided"
    );
    if (left.length === 0) return;
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
    .poll(async () => (await (await page.request.get(`/api/v1/runs/${RUN}`)).json()).finalized, {
      timeout: 30_000,
      message: "the run never became frozen after the confirmation",
    })
    .toBe(true);

  // Reload rather than assert the screen live-updates: it reads the run when it
  // mounts, and what matters is that the run is frozen and stays frozen.
  await page.reload();
  await expect(page.getByText("frozen")).toBeVisible({ timeout: 30_000 });
  await expect(generate).toHaveCount(0);

  // And the frozen report states the limits of what was verified. Read it from the
  // server rather than through the iframe, which the browser may still be showing
  // from before the freeze.
  const report = await page.request.get(`/api/v1/runs/${RUN}/report`);
  expect(report.status()).toBe(200);
  expect(await report.text()).toContain("What was checked");
});

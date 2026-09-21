/**
 * A hold must have two ways out (Phase 6.14a, ADR-041).
 *
 * Only one was ever offered on this card: accept, which asserts that the artifacts
 * belong to the delivery described on the form, with a reason recorded under the
 * submitter's name and printed on the final report. Somebody who had simply mistyped a
 * configuration id therefore had one button, and pressing it put a sentence they did
 * not mean onto a signed document.
 *
 * `POST /runs/{id}/cancel` has accepted a held run for as long as holds have existed
 * (`src/greenlight_ai/api/routers/runs.py`, the "queued" or "held" guard), and
 * `docs/user-training.md` has told people to cancel and correct the form. Nothing in
 * the product called it, so the instruction could not be followed.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactMismatch } from "@/lib/types";

const acceptMismatches = vi.fn();
const cancelRun = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    acceptMismatches: (...args: unknown[]) => acceptMismatches(...args),
    cancelRun: (...args: unknown[]) => cancelRun(...args),
  },
  ApiError: class extends Error {
    detail: string;
    constructor(detail: string) {
      super(detail);
      this.detail = detail;
    }
  },
}));

import { ArtifactMatchCard } from "./artifact-match-card";

const MISMATCH: ArtifactMismatch = {
  id: 1,
  field: "configuration_id",
  submitted: "CFG-1",
  found: "CFG-2",
  accepted_at: null,
  accepted_by: "",
  reason: "",
};

describe("a held run's two exits", () => {
  beforeEach(() => {
    acceptMismatches.mockReset().mockResolvedValue({});
    cancelRun.mockReset().mockResolvedValue({});
  });

  it("offers cancelling as well as accepting", () => {
    render(<ArtifactMatchCard runId={7} mismatches={[MISMATCH]} held />);
    expect(screen.getByRole("button", { name: /accept and run/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /form was wrong/i })).toBeTruthy();
  });

  it("cancels without asking for a reason, because nothing is being waived", async () => {
    const onAccepted = vi.fn();
    render(<ArtifactMatchCard runId={7} mismatches={[MISMATCH]} held onAccepted={onAccepted} />);

    await userEvent.click(screen.getByRole("button", { name: /form was wrong/i }));

    await waitFor(() => expect(cancelRun).toHaveBeenCalledWith(7));
    expect(acceptMismatches).not.toHaveBeenCalled();
    expect(onAccepted).toHaveBeenCalled();
  });

  it("still requires a reason to accept", async () => {
    render(<ArtifactMatchCard runId={7} mismatches={[MISMATCH]} held />);

    await userEvent.click(screen.getByRole("button", { name: /accept and run/i }));

    expect(acceptMismatches).not.toHaveBeenCalled();
    expect(screen.getByText(/say why these artifacts are the delivery you meant/i)).toBeTruthy();
  });

  it("offers neither once the run is no longer held", () => {
    render(<ArtifactMatchCard runId={7} mismatches={[MISMATCH]} held={false} />);
    expect(screen.queryByRole("button", { name: /accept and run/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /form was wrong/i })).toBeNull();
  });
});

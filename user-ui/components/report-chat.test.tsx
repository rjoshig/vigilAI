/**
 * The panel, and the three things it must not get wrong (Phase 8e).
 *
 * It does not appear when an administrator has not turned it on — asserted here as
 * well as on the endpoint, because a launcher drawn for a feature that refuses is a
 * worse experience than no launcher at all.
 *
 * It shows a citation only when the server sent one. The server checks every
 * identifier against the context it built, so a chip is a verified claim; when the
 * model did not say what its answer rested on, the panel says so and shows none.
 *
 * It keeps the conversation nowhere but here. Closing the panel clears it, which is
 * the decision the product made and the reason the Copy button exists.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatOpening } from "@/lib/types";

const chatOpening = vi.fn();
const askReport = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    chatOpening: (...args: unknown[]) => chatOpening(...args),
    askReport: (...args: unknown[]) => askReport(...args),
  },
  ApiError: class extends Error {
    detail = "";
  },
}));

const { ReportChat } = await import("./report-chat");

function opening(overrides: Partial<ChatOpening> = {}): ChatOpening {
  return {
    enabled: true,
    unavailable_reason: "",
    greeting: "I can see this frozen report — run VR-0042.",
    starters: ["What did nobody check?", "Which global rules applied here?"],
    cannot_see: "It reads what the tool derived from your files, never the rows.",
    changes_nothing: "It cannot change a decision.",
    not_saved: "The conversation is not saved.",
    trimmed: [],
    aggregates_included: false,
    max_questions_per_run: 20,
    questions_left_on_this_run: 20,
    questions_left_today: 50,
    ...overrides,
  };
}

async function openPanel(): Promise<void> {
  render(<ReportChat runId={42} />);
  const launcher = await screen.findByTestId("report-chat-launcher");
  await userEvent.click(launcher);
  await screen.findByTestId("report-chat-panel");
}

describe("whether it appears at all", () => {
  beforeEach(() => {
    chatOpening.mockReset();
    askReport.mockReset();
  });

  it("draws nothing when the feature is switched off", async () => {
    chatOpening.mockResolvedValue(opening({ enabled: false }));
    render(<ReportChat runId={42} />);
    await waitFor(() => expect(chatOpening).toHaveBeenCalled());
    expect(screen.queryByTestId("report-chat-launcher")).toBeNull();
  });

  it("draws nothing when the server cannot be reached", async () => {
    chatOpening.mockRejectedValue(new Error("down"));
    render(<ReportChat runId={42} />);
    await waitFor(() => expect(chatOpening).toHaveBeenCalled());
    expect(screen.queryByTestId("report-chat-launcher")).toBeNull();
  });

  it("offers a launcher when it is on", async () => {
    chatOpening.mockResolvedValue(opening());
    render(<ReportChat runId={42} />);
    expect(await screen.findByTestId("report-chat-launcher")).toBeTruthy();
  });
});

describe("what it says before it is asked anything", () => {
  beforeEach(() => {
    chatOpening.mockReset().mockResolvedValue(opening());
    askReport.mockReset();
  });

  it("shows the greeting the server wrote, and its three limits", async () => {
    await openPanel();
    expect(screen.getByText(/run VR-0042/)).toBeTruthy();
    expect(screen.getByText(/never the rows/)).toBeTruthy();
    expect(screen.getByText(/cannot change a decision/)).toBeTruthy();
    expect(screen.getByText(/not saved/)).toBeTruthy();
  });

  it("offers the starter questions the server built", async () => {
    await openPanel();
    expect(screen.getByText("What did nobody check?")).toBeTruthy();
  });

  it("says when the context was trimmed rather than hiding it", async () => {
    chatOpening.mockResolvedValue(opening({ trimmed: ["- 3 of 40 finding(s) were omitted."] }));
    await openPanel();
    expect(screen.getByTestId("report-chat-trimmed")).toBeTruthy();
  });
});

describe("asking", () => {
  beforeEach(() => {
    chatOpening.mockReset().mockResolvedValue(opening());
    askReport.mockReset();
  });

  it("shows the prose as it arrives and then the checked citations", async () => {
    askReport.mockImplementation(
      async (
        _runId: number,
        _question: string,
        _transcript: unknown,
        onDelta: (text: string) => void
      ) => {
        onDelta("Because ");
        onDelta("the state list differs.");
        return {
          citations: [{ id: "F-003", kind: "finding", label: "high: state list", anchor: "" }],
          unverified: false,
        };
      }
    );
    await openPanel();
    await userEvent.click(screen.getByText("What did nobody check?"));
    await screen.findByText(/the state list differs/);
    expect(screen.getByTestId("report-chat-citations").textContent).toContain("F-003");
    expect(screen.queryByTestId("report-chat-unverified")).toBeNull();
  });

  it("keeps the answer and says the citations are unverified", async () => {
    askReport.mockImplementation(
      async (
        _runId: number,
        _question: string,
        _transcript: unknown,
        onDelta: (text: string) => void
      ) => {
        onDelta("A complete answer.");
        return { citations: [], unverified: true };
      }
    );
    await openPanel();
    await userEvent.click(screen.getByText("What did nobody check?"));
    await screen.findByText("A complete answer.");
    expect(screen.getByTestId("report-chat-unverified")).toBeTruthy();
    expect(screen.queryByTestId("report-chat-citations")).toBeNull();
  });

  it("sends the earlier turns, and only them", async () => {
    askReport.mockResolvedValue({ citations: [], unverified: false });
    await openPanel();
    await userEvent.click(screen.getByText("What did nobody check?"));
    await waitFor(() => expect(askReport).toHaveBeenCalledTimes(1));
    expect(askReport.mock.calls[0][2]).toEqual([]);

    await userEvent.type(
      screen.getByLabelText("Your question about this report"),
      "And the rules?"
    );
    await userEvent.click(screen.getByLabelText("Send"));
    await waitFor(() => expect(askReport).toHaveBeenCalledTimes(2));
    expect(askReport.mock.calls[1][2]).toHaveLength(2);
  });
});

describe("closing it ends the conversation", () => {
  beforeEach(() => {
    chatOpening.mockReset().mockResolvedValue(opening());
    askReport.mockReset().mockResolvedValue({ citations: [], unverified: false });
  });

  it("clears the transcript, because it lives nowhere else", async () => {
    await openPanel();
    await userEvent.click(screen.getByText("What did nobody check?"));
    await waitFor(() => expect(askReport).toHaveBeenCalled());

    await userEvent.click(screen.getByLabelText("Close"));
    await userEvent.click(await screen.findByTestId("report-chat-launcher"));
    await screen.findByTestId("report-chat-panel");
    // The starters are back, which is only true of a conversation with no turns.
    expect(screen.getByTestId("report-chat-starters")).toBeTruthy();
  });

  it("closes on Escape, so the panel can be left from the keyboard", async () => {
    await openPanel();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("report-chat-panel")).toBeNull());
  });

  it("writes nothing to browser storage", async () => {
    await openPanel();
    await userEvent.click(screen.getByText("What did nobody check?"));
    await waitFor(() => expect(askReport).toHaveBeenCalled());
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});

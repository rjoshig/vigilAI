/**
 * The Train AI mode indicator, rendered (Phase 6.4a).
 *
 * The indicator is drawn in both states on purpose: "off" is a fact a person should be
 * able to see, not merely the absence of a control. The UI suites covered the client
 * that reads the switch but never the thing a person actually looks at, which is the
 * test this closes.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrainingModeLine } from "./app-shell";
import { TRAIN_AI_TAG_LABEL, TrainAiTag, TRAIN_AI_HINT } from "./train-ai-tag";

describe("the Train AI mode indicator", () => {
  it("says the mode is on, and says why it matters", () => {
    render(<TrainingModeLine enabled={true} />);

    expect(screen.getByText("Train AI mode on")).toBeInTheDocument();
    const line = screen.getByLabelText(/Train AI mode on/);
    expect(line).toHaveAttribute("title", TRAIN_AI_HINT);
  });

  it("says the mode is off rather than showing nothing", () => {
    render(<TrainingModeLine enabled={false} />);

    expect(screen.getByText("Train AI mode off")).toBeInTheDocument();
    expect(screen.getByLabelText(/Train AI mode off/)).toBeInTheDocument();
  });

  it("marks a control that exists only because the mode is on", () => {
    render(<TrainAiTag />);

    const tag = screen.getByText(TRAIN_AI_TAG_LABEL);
    expect(tag).toBeInTheDocument();
    expect(tag).toHaveAttribute("title", TRAIN_AI_HINT);
  });
});

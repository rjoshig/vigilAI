/**
 * How an open help tip is dismissed.
 *
 * A tip used to close only when the control that opened it was clicked a second time,
 * so reading one and carrying on meant aiming at a 16-pixel target. It now closes on
 * the next click wherever it lands.
 *
 * What this suite can and cannot show: the dismiss sheet's handler is exercised
 * directly, because a test DOM has no layout and so cannot hit-test a click at a point
 * on the screen. That the sheet *covers* the page is a matter of it being `fixed
 * inset-0` above the button's stacking context, which is asserted as markup rather
 * than as behaviour.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Explain, FieldEffect } from "./explain";

let tooltips = true;
let setupMarkers = true;
vi.mock("@/components/palette-provider", () => ({
  usePalette: () => ({ tooltips, setupMarkers }),
}));

function open() {
  render(<Explain label="What is this for?">Why this surface exists.</Explain>);
  fireEvent.click(screen.getByLabelText("What is this for?"));
  expect(screen.getByRole("note")).toBeInTheDocument();
}

describe("a help tip", () => {
  beforeEach(() => {
    tooltips = true;
    setupMarkers = true;
  });

  it("opens on the question mark", () => {
    open();
    expect(screen.getByText("Why this surface exists.")).toBeInTheDocument();
  });

  it("closes when the click lands anywhere else on the page", () => {
    open();
    fireEvent.click(screen.getByTestId("explain-dismiss"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("closes when the click lands on the tip itself", () => {
    open();
    fireEvent.click(screen.getByRole("note"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("closes on the question mark again, which is the keyboard path", () => {
    open();
    fireEvent.click(screen.getByLabelText("What is this for?"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    open();
    fireEvent.keyDown(screen.getByLabelText("What is this for?"), { key: "Escape" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("covers the page while open, so no click can reach what is underneath", () => {
    open();
    expect(screen.getByTestId("explain-dismiss")).toHaveClass("fixed", "inset-0");
  });

  it("leaves nothing behind when it is closed", () => {
    open();
    fireEvent.click(screen.getByTestId("explain-dismiss"));
    expect(screen.queryByTestId("explain-dismiss")).not.toBeInTheDocument();
  });

  it("renders nothing at all where the deployment switches help off", () => {
    tooltips = false;
    render(<Explain label="What is this for?">Hidden.</Explain>);
    expect(screen.queryByLabelText("What is this for?")).not.toBeInTheDocument();
  });
});

describe("a marker saying what a field does", () => {
  beforeEach(() => {
    tooltips = true;
    setupMarkers = true;
  });

  it("says a setup-only field is not used in a run, in plain words", () => {
    render(<FieldEffect kind="reference" note="These example files." />);
    expect(screen.getByText("Used for setup, not for runs")).toBeInTheDocument();
  });

  it("hides the setup-only marker where the console switches it off", () => {
    setupMarkers = false;
    render(<FieldEffect kind="reference" note="These example files." />);
    expect(screen.queryByText("Used for setup, not for runs")).not.toBeInTheDocument();
  });

  it("keeps saying a field reaches the model whatever the switches say", () => {
    setupMarkers = false;
    tooltips = false;
    render(<FieldEffect kind="model" note="Read at extraction." />);
    expect(screen.getByText("Helps the AI")).toBeInTheDocument();
  });

  it("keeps saying a field is compared by code whatever the switches say", () => {
    setupMarkers = false;
    tooltips = false;
    render(<FieldEffect kind="code" />);
    expect(screen.getByText("Checked by code")).toBeInTheDocument();
  });
});

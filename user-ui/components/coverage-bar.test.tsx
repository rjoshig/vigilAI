/**
 * Coverage as a picture (Phase 6.21f).
 *
 * The bar exists so somebody can see whether a delivery was mostly checked before
 * reading four numbers. What these pin down is that it never lies about the shape:
 * a single untraced requirement out of two hundred must still be visible, because that
 * is the segment somebody most needs to notice, and a bar that rounds it away is worse
 * than no bar at all.
 */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CoverageBar } from "./coverage-bar";

/** The bar's own children. `div > div` would also match the bar inside the wrapper. */
function segments(container: HTMLElement): HTMLElement[] {
  return Array.from(container.firstElementChild?.children ?? []) as HTMLElement[];
}

function widths(container: HTMLElement): number[] {
  return segments(container).map((node) => parseFloat(node.style.width));
}

describe("the coverage bar", () => {
  it("draws one segment per state that has any", () => {
    const { container } = render(
      <CoverageBar counts={{ checked: 6, traced_unchecked: 2, manual: 1, untraced: 1 }} />
    );
    expect(widths(container)).toHaveLength(4);
  });

  it("leaves out a state with none, rather than drawing a zero-width sliver", () => {
    const { container } = render(<CoverageBar counts={{ checked: 10 }} />);
    expect(widths(container)).toEqual([100]);
  });

  it("keeps a single requirement out of two hundred visible", () => {
    // A quarter of a percent rounds to nothing on any screen, and the one it would
    // vanish from is `untraced` — the state that means nothing implements this.
    const { container } = render(<CoverageBar counts={{ checked: 199, untraced: 1 }} />);
    const [, sliver] = widths(container);
    expect(sliver).toBeGreaterThanOrEqual(1.5);
  });

  it("draws nothing at all when there are no requirements", () => {
    const { container } = render(<CoverageBar counts={{}} />);
    expect(container.firstChild).toBeNull();
  });

  it("is hidden from a screen reader, because the counts beside it are the words", () => {
    const { container } = render(<CoverageBar counts={{ checked: 1 }} />);
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
  });

  it("puts the best-understood state first and the least last", () => {
    const { container } = render(
      <CoverageBar counts={{ untraced: 1, checked: 1, manual: 1, traced_unchecked: 1 }} />
    );
    const classes = segments(container).map((node) => node.className);
    expect(classes).toEqual(["bg-success", "bg-warn", "bg-info", "bg-destructive"]);
  });
});

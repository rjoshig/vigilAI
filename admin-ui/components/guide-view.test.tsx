/**
 * The Guide, as a person meets it (Phase 6.19b).
 *
 * Two things are worth pinning. The renderer draws each kind of block, because the
 * content is generated and a block shape nobody drew would silently disappear from a
 * screen whose whole job is to be complete. And the contents list carries every section,
 * because the Guide is written for somebody who arrived with a question rather than
 * somebody reading it front to back.
 *
 * The content itself is not asserted here. It comes from the training document, and
 * `tests/docs/test_guides.py` is where the two are held together.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GuideSection } from "@/lib/guide";

import { GuideView } from "./guide-view";
import { GUIDE } from "@/lib/guide.generated";

const SAMPLE: GuideSection[] = [
  {
    id: "s1",
    title: "What this does",
    blocks: [
      { kind: "text", spans: [{ text: "Plain " }, { text: "emphasis", bold: true }] },
      { kind: "heading", spans: [{ text: "A sub-heading" }] },
      { kind: "list", items: [[{ text: "a bullet" }]] },
      { kind: "ordered", items: [[{ text: "a step" }]] },
      {
        kind: "table",
        head: [[{ text: "Where" }], [{ text: "What" }]],
        rows: [[[{ text: "a cell", bold: true }], [{ text: "another cell" }]]],
      },
      { kind: "text", spans: [{ text: "a_setting", code: true }] },
      { kind: "text", spans: [{ text: "their own words", italic: true }] },
    ],
  },
  { id: "s2", title: "What it will not catch", blocks: [] },
];

describe("the Guide renderer", () => {
  it("draws every kind of block the generator can produce", () => {
    render(<GuideView sections={SAMPLE} />);

    expect(screen.getByText("Plain")).toBeInTheDocument();
    expect(screen.getByText("emphasis").tagName).toBe("STRONG");
    expect(screen.getByText("A sub-heading")).toBeInTheDocument();
    expect(screen.getByText("a bullet").tagName).toBe("LI");
    expect(screen.getByText("a step").tagName).toBe("LI");
    expect(screen.getByText("Where").closest("th")).not.toBeNull();
    // Cells carry emphasis too, and a cell that reached the screen as `**user**` was
    // the parser gap this test was written for.
    expect(screen.getByText("a cell").tagName).toBe("STRONG");
    expect(screen.getByText("another cell").closest("td")).not.toBeNull();
    expect(screen.getByText("a_setting").tagName).toBe("CODE");
    expect(screen.getByText("their own words").tagName).toBe("EM");
  });

  it("lists every section as a question, before any of the answers", () => {
    render(<GuideView sections={SAMPLE} />);

    const contents = screen.getByRole("navigation", { name: "What this guide answers" });
    expect(contents).toBeInTheDocument();
    for (const section of SAMPLE) {
      expect(contents.querySelector(`a[href="#${section.id}"]`)).not.toBeNull();
    }
  });

  it("renders a section with no blocks rather than failing on it", () => {
    render(<GuideView sections={SAMPLE} />);

    expect(screen.getByRole("heading", { name: "What it will not catch" })).toBeInTheDocument();
  });
});

describe("the generated content", () => {
  it("is not empty, and every section has a title and an id", () => {
    expect(GUIDE.length).toBeGreaterThan(3);
    for (const section of GUIDE) {
      expect(section.id).toMatch(/^s\d+$/);
      expect(section.title.length).toBeGreaterThan(3);
      expect(section.blocks.length).toBeGreaterThan(0);
    }
  });

  it("carries no leftover markdown, which would mean the parser missed something", () => {
    const text = JSON.stringify(GUIDE);
    expect(text).not.toContain("**");
    expect(text).not.toContain("```");
    expect(text).not.toMatch(/\]\(/);
    // A lone asterisk means an italic run the parser did not resolve. JSON escapes
    // nothing here, so any survivor is markdown that would print as punctuation.
    expect(text).not.toContain("*");
  });
});

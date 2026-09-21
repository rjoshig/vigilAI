/**
 * The layout editor, and the loop it closes (Phase 6.21b).
 *
 * The screen's whole job is to make one thing obvious: the AI read a name for you, and
 * recording it means nobody is asked again. So what these pin down is the wording and
 * the flow around that offer — that an already-recorded name stops being offered, that
 * accepting calls the endpoint that records it, and that an entry with no spelling is
 * not saved, because a half-written row that looks applied is worse than no row.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactType, LayoutSuggestion } from "@/lib/types";

vi.mock("@/components/palette-provider", () => ({
  usePalette: () => ({ tooltips: true, setupMarkers: true }),
}));

const getLayoutSuggestions = vi.fn();
const acceptLayout = vi.fn();
const saveLayout = vi.fn();
const listScopes = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    getLayoutSuggestions: (...args: unknown[]) => getLayoutSuggestions(...args),
    acceptLayout: (...args: unknown[]) => acceptLayout(...args),
    saveLayout: (...args: unknown[]) => saveLayout(...args),
    listScopes: (...args: unknown[]) => listScopes(...args),
  },
  ApiError: class extends Error {
    detail = "";
  },
}));

const { LayoutEditor } = await import("./layout-editor");

function type(overrides: Partial<ArtifactType> = {}): ArtifactType {
  return {
    id: 1,
    key: "counts",
    label: "Number flow",
    kind: "report",
    description: "",
    ai_context: "",
    is_active: true,
    is_required: false,
    is_builtin: true,
    sort_order: 10,
    samples: [],
    sheets: [],
    runs_using: 0,
    guide: [],
    layout: [],
    version: 0,
    ...overrides,
  } as ArtifactType;
}

function suggestion(overrides: Partial<LayoutSuggestion> = {}): LayoutSuggestion {
  return {
    artifact: "counts",
    kind: "label",
    wanted: "Accepts",
    found: "Accepted total",
    confidence: 0.88,
    reason: "An accepted total is the count that passed every filter.",
    seen: 3,
    run_ids: [1, 2, 3],
    already_listed: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listScopes.mockResolvedValue([]);
  getLayoutSuggestions.mockResolvedValue({ suggestions: [] });
});

describe("the offer", () => {
  it("says what the AI read, how sure it was, and why", async () => {
    getLayoutSuggestions.mockResolvedValue({ suggestions: [suggestion()] });
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    expect(await screen.findByText(/The AI read 1 name for you/)).toBeInTheDocument();
    // "Accepts" is also in the paragraph above, which is the point of that
    // paragraph: the reader should recognise the name being talked about.
    expect(screen.getAllByText("Accepts").length).toBeGreaterThan(0);
    expect(screen.getByText("Accepted total")).toBeInTheDocument();
    expect(screen.getByText("88% sure")).toBeInTheDocument();
    expect(screen.getByText("3 runs")).toBeInTheDocument();
    expect(screen.getByText(/passed every filter/)).toBeInTheDocument();
  });

  it("stops offering a name that is already recorded", async () => {
    getLayoutSuggestions.mockResolvedValue({
      suggestions: [suggestion({ already_listed: true })],
    });
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    await waitFor(() => expect(getLayoutSuggestions).toHaveBeenCalled());
    expect(screen.queryByText(/The AI read/)).not.toBeInTheDocument();
  });

  it("only shows this type's own readings", async () => {
    getLayoutSuggestions.mockResolvedValue({
      suggestions: [suggestion({ artifact: "dirt", wanted: "Attributes" })],
    });
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    await waitFor(() => expect(getLayoutSuggestions).toHaveBeenCalled());
    expect(screen.queryByText(/The AI read/)).not.toBeInTheDocument();
  });

  it("records the name on the type when accepted", async () => {
    getLayoutSuggestions.mockResolvedValue({ suggestions: [suggestion()] });
    acceptLayout.mockResolvedValue(type());
    const onSaved = vi.fn();
    render(<LayoutEditor type={type()} busy={false} onSaved={onSaved} />);

    await userEvent.click(await screen.findByRole("button", { name: /Record it/ }));

    expect(acceptLayout).toHaveBeenCalledWith("counts", "label", "Accepts", "Accepted total");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("degrades to no opinion when the offers cannot be read", async () => {
    getLayoutSuggestions.mockRejectedValue(new Error("nope"));
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    await waitFor(() => expect(getLayoutSuggestions).toHaveBeenCalled());
    expect(await screen.findByText(/Nothing recorded/)).toBeInTheDocument();
  });
});

describe("the map", () => {
  it("says the ordinary state is empty, rather than looking unconfigured", async () => {
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);
    expect(await screen.findByText(/most deliveries are read without one/)).toBeInTheDocument();
  });

  it("shows what is already recorded", async () => {
    render(
      <LayoutEditor
        type={type({
          layout: [
            {
              scope: "",
              kind: "sheet",
              wanted: "Attributes",
              names: ["Attribute Summary"],
              note: "",
              added_by: "",
            },
          ],
        })}
        busy={false}
        onSaved={vi.fn()}
      />
    );

    expect(await screen.findByDisplayValue("Attributes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Attribute Summary")).toBeInTheDocument();
  });

  it("does not save a row with no spelling on it", async () => {
    saveLayout.mockResolvedValue(type());
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: /Add a name/ }));
    await userEvent.click(screen.getByRole("button", { name: /Save layout/ }));

    expect(saveLayout).toHaveBeenCalledWith("counts", []);
  });

  it("splits several spellings on commas", async () => {
    saveLayout.mockResolvedValue(type());
    render(<LayoutEditor type={type()} busy={false} onSaved={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: /Add a name/ }));
    await userEvent.type(screen.getByLabelText("The checks look for"), "Accepts");
    await userEvent.type(
      screen.getByLabelText("This delivery calls it"),
      "Accepted total, Records accepted"
    );
    await userEvent.click(screen.getByRole("button", { name: /Save layout/ }));

    expect(saveLayout).toHaveBeenCalledWith("counts", [
      expect.objectContaining({ names: ["Accepted total", "Records accepted"] }),
    ]);
  });
});

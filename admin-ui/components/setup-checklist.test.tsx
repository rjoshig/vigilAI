/**
 * What each step of the setup path does to a run (Phase 6.19d).
 *
 * The card is navigation, so the question somebody asks it is not "is this stored" but
 * "which of these seven afternoons changes what the AI finds". These pin that answer
 * down against the register rather than against the wording of the day: the three steps
 * whose product reaches a prompt carry **Helps the AI**, the three code evaluates carry
 * **Checked by code**, and the samples carry the one marker an administrator may switch
 * off — which, being switched off, must take nothing else with it.
 */

import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactType } from "@/lib/types";

const setupMarkers = { value: true };

vi.mock("@/components/palette-provider", () => ({
  usePalette: () => ({ tooltips: true, setupMarkers: setupMarkers.value }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const listScopes = vi.fn();
const listChecks = vi.fn();
const listMeaning = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    listScopes: () => listScopes(),
    listChecks: () => listChecks(),
    listMeaning: () => listMeaning(),
  },
}));

const { SetupChecklist } = await import("./setup-checklist");

function reportType(overrides: Partial<ArtifactType> = {}): ArtifactType {
  return {
    id: 1,
    key: "dirt",
    label: "DIRT",
    kind: "report",
    description: "",
    ai_context: "",
    is_active: true,
    is_required: true,
    sort_order: 1,
    is_builtin: true,
    samples: [],
    sheets: [],
    runs_using: 0,
    guide: [],
    layout: [],
    version: 1,
    ...overrides,
  };
}

/** Render and let the three count fetches settle, so no assertion races them. */
async function show(): Promise<void> {
  await act(async () => {
    render(<SetupChecklist types={[reportType()]} />);
  });
}

describe("the marker on each step", () => {
  beforeEach(() => {
    setupMarkers.value = true;
    listScopes.mockResolvedValue([]);
    listChecks.mockResolvedValue([]);
    listMeaning.mockResolvedValue([]);
  });

  it("says Helps the AI on the three steps whose product reaches a prompt", async () => {
    await show();
    expect(screen.getAllByText("Helps the AI")).toHaveLength(3);
  });

  it("says Checked by code on the three steps code evaluates", async () => {
    await show();
    expect(screen.getAllByText("Checked by code")).toHaveLength(3);
  });

  it("marks the samples as setup-only, which is the one an admin may switch off", async () => {
    await show();
    expect(screen.getAllByText("Used for setup, not for runs")).toHaveLength(1);
  });

  it("takes nothing but the setup marker away when that marker is switched off", async () => {
    setupMarkers.value = false;
    await show();
    expect(screen.queryByText("Used for setup, not for runs")).toBeNull();
    expect(screen.getAllByText("Helps the AI")).toHaveLength(3);
    expect(screen.getAllByText("Checked by code")).toHaveLength(3);
  });

  it("says in words that the card itself reaches nothing", async () => {
    await show();
    expect(screen.getByText(/reaches nothing and is stored nowhere/)).toBeTruthy();
  });
});

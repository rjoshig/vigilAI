/**
 * The console shows each person their own job (Phase 6.20d, ADR-049).
 *
 * Two separate claims, and the second is the one that matters:
 *
 * 1. The rail carries only the screens this person may use.
 * 2. A screen reached by **typing its URL** renders a refusal rather than itself —
 *    because a hidden link is not access control, and somebody who has bookmarked
 *    `/settings` never sees the rail at all.
 *
 * What these tests cannot show is that the screen is actually closed: the API decides
 * that, and `tests/api/test_capabilities.py` is where it is proved. This is the
 * courtesy on top of the control.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Capability } from "@/lib/types";

import { AppShell } from "./app-shell";

let held: Capability[] = [];

vi.mock("@/components/auth-gate", () => ({
  useAuth: () => ({
    user: null,
    authEnabled: true,
    can: (capability: Capability) => held.includes(capability),
    signOut: () => undefined,
  }),
}));

vi.mock("@/components/palette-provider", () => ({
  usePalette: () => ({ tagline: "" }),
  PalettePicker: () => null,
}));

vi.mock("@/components/theme-picker", () => ({ PalettePicker: () => null }));
vi.mock("@/components/notice-bar", () => ({ NoticeBar: () => null }));
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light", setTheme: () => {} }),
}));
// Never resolves: the Train AI indicator is not what is under test, and a state
// update landing after the assertions only produces act() noise.
vi.mock("@/lib/api", () => ({
  api: { getTrainingConfig: () => new Promise(() => undefined) },
}));

let pathname = "/usage";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

const REVIEWER: Capability[] = [
  "view_admin",
  "approve_training",
  "manage_rules",
  "teach_model",
  "manage_reference",
];

const ADMIN: Capability[] = [
  ...REVIEWER,
  "manage_privacy",
  "manage_artifacts",
  "manage_programmes",
  "manage_meaning",
  "manage_users",
  "manage_settings",
];

function shell() {
  render(
    <AppShell>
      <p>the screen itself</p>
    </AppShell>
  );
}

describe("the sidebar", () => {
  beforeEach(() => {
    pathname = "/usage";
  });

  it("shows an administrator every screen", () => {
    held = ADMIN;
    shell();

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Meaning")).toBeInTheDocument();
  });

  it("shows a reviewer what judging the work needs, and nothing that defines the deployment", () => {
    held = REVIEWER;
    shell();

    expect(screen.getByText("Training")).toBeInTheDocument();
    expect(screen.getByText("Checks")).toBeInTheDocument();
    expect(screen.getByText("Reference data")).toBeInTheDocument();
    expect(screen.queryByText("Settings")).not.toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Artifact types")).not.toBeInTheDocument();
    expect(screen.queryByText("Delivery programmes")).not.toBeInTheDocument();
    expect(screen.queryByText("Meaning")).not.toBeInTheDocument();
  });
});

describe("a screen reached by its URL", () => {
  it("renders itself when the screen is this person's", () => {
    held = REVIEWER;
    pathname = "/training";
    shell();

    expect(screen.getByText("the screen itself")).toBeInTheDocument();
  });

  it("renders a refusal when it is not, rather than an empty page", () => {
    held = REVIEWER;
    pathname = "/settings";
    shell();

    expect(screen.queryByText("the screen itself")).not.toBeInTheDocument();
    expect(screen.getByText("This screen is for administrators")).toBeInTheDocument();
  });

  it("matches the longest prefix, so one screen does not answer for another", () => {
    held = REVIEWER;
    pathname = "/reference";
    shell();

    // `/rules` is a prefix of nothing here, but `/reference` and `/rules` both begin
    // with `/r`: the wrong match would hand Reference data the Rules capability.
    expect(screen.getByText("the screen itself")).toBeInTheDocument();
  });

  it("lets the dashboard through, which the sign-in gate has already guarded", () => {
    held = REVIEWER;
    pathname = "/";
    shell();

    expect(screen.getByText("the screen itself")).toBeInTheDocument();
  });
});

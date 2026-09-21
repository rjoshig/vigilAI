/**
 * Who is offered the admin console (Phase 6.20d, ADR-049).
 *
 * The link used to be unconditional, which is the thing that prompted the three roles:
 * somebody who could change nothing in the console was still invited into it. It now
 * appears only for an account that includes the console.
 *
 * Two cases are deliberately *shown* the link rather than hidden from it:
 *
 * - **Login off**, the shipped default. There is one placeholder account holding
 *   everything, so the sidebar is exactly what it always was (ADR-022).
 * - **Login on for the console but not for this app.** The user app then has no idea
 *   who is looking at it, and a link to a console that asks for its own sign-in is
 *   more use than no link at all.
 *
 * Hiding the link is a courtesy, never the control: `tests/api/test_capabilities.py`
 * is where the console is actually closed.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CurrentUser } from "@/lib/types";

import { AppShell } from "./app-shell";

let user: CurrentUser | null = null;

vi.mock("@/components/auth-gate", () => ({
  useAuth: () => ({
    user,
    canViewAdmin: user === null || user.capabilities.includes("view_admin"),
    signOut: async () => undefined,
  }),
}));

let guideOn = true;
vi.mock("@/components/palette-provider", () => ({
  usePalette: () => ({ tagline: "", guide: guideOn }),
}));
vi.mock("@/components/theme-picker", () => ({ PalettePicker: () => null }));
vi.mock("@/components/notice-bar", () => ({ NoticeBar: () => null }));
vi.mock("@/components/observation-dialog", () => ({ useTrainingEnabled: () => false }));
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light", setTheme: () => {} }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/runs" }));

function account(capabilities: string[]): CurrentUser {
  return {
    id: 2,
    name: "A person",
    email: "person@localhost",
    roles: ["user"],
    capabilities,
    is_admin: false,
    is_placeholder: false,
    must_change_password: false,
  };
}

function shell() {
  render(
    <AppShell>
      <p>a run</p>
    </AppShell>
  );
}

describe("the Admin console link", () => {
  beforeEach(() => {
    user = null;
    guideOn = true;
  });

  it("is there while login is off, exactly as it always was", () => {
    shell();

    expect(screen.getByText("Admin console")).toBeInTheDocument();
  });

  it("is there for a reviewer, whose console it is", () => {
    user = account(["view_admin", "approve_training"]);
    shell();

    expect(screen.getByText("Admin console")).toBeInTheDocument();
  });

  it("is not there for somebody who can change nothing in it", () => {
    user = account([]);
    shell();

    expect(screen.queryByText("Admin console")).not.toBeInTheDocument();
  });

  it("never takes the rest of the sidebar with it", () => {
    user = account([]);
    shell();

    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.getByText("New run")).toBeInTheDocument();
  });
});

describe("the Guide link", () => {
  beforeEach(() => {
    user = null;
    guideOn = true;
  });

  it("is in the sidebar by default, so it is found without being told about", () => {
    shell();

    expect(screen.getByText("Guide")).toBeInTheDocument();
  });

  it("goes when the deployment switches it off", () => {
    guideOn = false;
    shell();

    expect(screen.queryByText("Guide")).not.toBeInTheDocument();
    expect(screen.getByText("Runs")).toBeInTheDocument();
  });

  it("is there for a plain user, who needs it most", () => {
    user = account([]);
    shell();

    expect(screen.getByText("Guide")).toBeInTheDocument();
  });
});

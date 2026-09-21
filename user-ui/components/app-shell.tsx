"use client";

/** The sidebar and page frame shared by every screen. */

import {
  ExternalLink,
  FileSearch,
  FileText,
  FolderGit2,
  LayoutList,
  Lightbulb,
  Moon,
  LogOut,
  Plus,
  ShieldCheck,
  Sun,
  BarChart3,
} from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { NoticeBar } from "@/components/notice-bar";
import { usePalette } from "@/components/palette-provider";
import { useAuth } from "@/components/auth-gate";
import { useTrainingEnabled } from "@/components/observation-dialog";
import { TRAIN_AI_HINT } from "@/components/train-ai-tag";
import { Logo } from "@/components/logo";
import { PalettePicker } from "@/components/theme-picker";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

/**
 * Where the admin console lives. A separate app on its own port with its own sign-in
 * switch (ADR-022), so this is a plain external link rather than a route. Overridable
 * because the port is the developer default, not the deployed URL.
 */
const ADMIN_URL = process.env.NEXT_PUBLIC_ADMIN_URL ?? "http://localhost:3001";

const NAV: NavItem[] = [
  { href: "/runs", label: "Runs", icon: LayoutList },
  { href: "/runs/new", label: "New run", icon: Plus },
  { href: "/configs", label: "Config history", icon: FolderGit2 },
];

/** Shown only while Train AI mode is on, so the app is unchanged when it is off. */
const TRAINING_NAV: NavItem = {
  href: "/observations",
  label: "My observations",
  icon: Lightbulb,
};

/**
 * Explore a sample (Phase 6.1e). Always available: looking at an example of what the
 * tool accepts is useful whatever the mode says, and it is where a reviewer goes to
 * point at something the tool has not raised.
 */
const EXPLORE_NAV: NavItem = {
  href: "/explore",
  label: "Explore a sample",
  icon: FileSearch,
};

/**
 * The mode indicator (6.4a). Drawn in both states, because "off" is a fact a person
 * should be able to see and not merely the absence of a control.
 */
export function TrainingModeLine({ enabled }: { enabled: boolean }) {
  return (
    <div
      className="flex items-center gap-1.5 px-4 pb-3 text-[0.6875rem] text-muted-foreground"
      title={TRAIN_AI_HINT}
      aria-label={`Train AI mode ${enabled ? "on" : "off"}. ${TRAIN_AI_HINT}`}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-2 w-2 flex-shrink-0 rounded-full",
          enabled ? "train-live bg-success" : "bg-muted-foreground/50"
        )}
      />
      <span>Train AI mode {enabled ? "on" : "off"}</span>
    </div>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  // Rendering the icon before mount would mismatch the server markup, because the
  // server cannot know which theme the browser resolved.
  const isDark = mounted && resolvedTheme === "dark";
  return (
    <Button
      variant="outline"
      size="icon"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {mounted ? (
        isDark ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )
      ) : (
        <span className="h-4 w-4" />
      )}
    </Button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Null while login is off, which is the shipped default, so the footer stays as it was.
  const { user, canViewAdmin, signOut } = useAuth();
  const trainingEnabled = useTrainingEnabled();
  const { tagline } = usePalette();
  const nav = trainingEnabled ? [...NAV, EXPLORE_NAV, TRAINING_NAV] : [...NAV, EXPLORE_NAV];

  return (
    <div className="flex min-h-screen">
      <aside className="app-sidebar sticky top-0 flex h-screen w-56 flex-shrink-0 flex-col border-r bg-card text-card-foreground">
        {/* The box is the one theme-independent surface in the rail: the mark's dark
            housing has to read on the navy palette as well as on white. */}
        <Link href="/" aria-label="Greenlight AI home" className="flex items-center gap-2.5 p-4">
          <span className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-lg bg-tertiary">
            <Logo size={30} />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-base font-bold leading-tight tracking-tight">
              {/* The name never breaks; the chip drops to its own line when the rail
                  is too narrow for both. */}
              <span className="whitespace-nowrap">Greenlight AI</span>
              <span className="rounded-full bg-tertiary px-1.5 py-px text-[0.6rem] font-bold uppercase tracking-wider text-tertiary-foreground">
                User
              </span>
            </div>
            {tagline ? (
              <div className="text-[0.625rem] text-muted-foreground">{tagline}</div>
            ) : null}
          </div>
        </Link>
        <TrainingModeLine enabled={trainingEnabled} />

        <nav className="flex flex-1 flex-col gap-0.5 px-2.5 pt-2">
          <div className="px-2 pb-1 text-[0.625rem] font-semibold uppercase tracking-wider text-muted-foreground">
            Menu
          </div>
          {nav.map((item) => {
            const active =
              item.href === "/runs" ? pathname === "/runs" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium",
                  active
                    ? "bg-primary/10 font-semibold text-primary"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                )}
              >
                <Icon className="h-[1.125rem] w-[1.125rem]" />
                <span>{item.label}</span>
              </Link>
            );
          })}
          {/* Only for somebody whose account includes the console (ADR-049). Inviting
              everybody into a console they cannot change anything in is what prompted
              the three roles; while login is off there is one account that holds
              everything, so the link is there exactly as it was. */}
          {canViewAdmin ? (
            <a
              href={ADMIN_URL}
              target="_blank"
              rel="noreferrer"
              className="mt-1 flex items-center gap-3 rounded-md border border-dashed px-2.5 py-2 text-sm font-medium text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            >
              <ShieldCheck className="h-[1.125rem] w-[1.125rem]" />
              <span>Admin console</span>
              <ExternalLink className="ml-auto h-3.5 w-3.5" />
            </a>
          ) : null}
        </nav>

        {user ? (
          <div className="flex items-center justify-between gap-2 border-t p-3 text-xs">
            <span className="min-w-0">
              <span className="block truncate font-medium text-foreground">{user.name}</span>
              <span className="block truncate text-muted-foreground">{user.email}</span>
            </span>
            <Button
              variant="outline"
              size="icon"
              aria-label="Sign out"
              title="Sign out"
              onClick={() => void signOut()}
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        ) : null}

        <div className="flex justify-center border-t px-2 py-1.5">
          <PalettePicker />
        </div>
        <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            user-ui :3000
          </span>
          <ThemeToggle />
        </div>
      </aside>

      <main className="h-screen min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[84rem] px-6 pb-12 pt-5">
          <NoticeBar audience="user" />
          {children}
        </div>
      </main>
    </div>
  );
}

export { BarChart3 };

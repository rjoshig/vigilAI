"use client";

/** The admin sidebar and page frame. Its own URL and port, separate from user-ui. */

import {
  BookMarked,
  ClipboardCheck,
  Gauge,
  GraduationCap,
  Layers,
  Lightbulb,
  Moon,
  LogOut,
  Scale,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  UserCog,
  Waypoints,
} from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth-gate";
import { Logo } from "@/components/logo";
import { PalettePicker } from "@/components/theme-picker";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV: NavItem[] = [
  { href: "/tell", label: "Tell the tool", icon: Lightbulb },
  { href: "/artifacts", label: "Artifact types", icon: BookMarked },
  { href: "/scopes", label: "Delivery programmes", icon: Layers },
  { href: "/meaning", label: "Meaning", icon: Waypoints },
  { href: "/checks", label: "Checks", icon: ClipboardCheck },
  { href: "/compliance", label: "Compliance rules", icon: ShieldCheck },
  { href: "/rules", label: "Rules", icon: Scale },
  { href: "/training", label: "Training", icon: GraduationCap },
  { href: "/reference", label: "Reference data", icon: Settings },
  { href: "/usage", label: "Usage", icon: Gauge },
  { href: "/users", label: "Users", icon: UserCog },
  { href: "/settings", label: "Settings", icon: SlidersHorizontal },
];

const TRAINING_MODE_HINT =
  "Reviewers can record observations while this is on; nothing they write changes anything until it is approved here.";

/**
 * Whether Train AI mode is on, shown in both states so "off" is a visible state and not
 * an absence. It is re-read on every route change, because the switch lives on the
 * Settings page and an administrator who flips it expects the sidebar to follow when
 * they navigate away.
 */
function TrainingModeIndicator({ pathname }: { pathname: string }) {
  const [enabled, setEnabled] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    api
      .getTrainingConfig()
      .then((config) => {
        if (!cancelled) setEnabled(config.enabled);
      })
      .catch(() => {
        // An unreachable API says nothing about the mode, so the line is left as it was.
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (enabled === null) return null;

  return (
    <div
      className="mx-4 mb-2 flex items-center gap-1.5 text-[0.7rem] text-muted-foreground"
      title={TRAINING_MODE_HINT}
      data-testid="training-mode-indicator"
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-2 w-2 rounded-full",
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

/** The signed-in person and sign-out appear only when login is actually on. */
function SidebarFooter() {
  const { user, authEnabled, signOut } = useAuth();

  return (
    <>
      <div className="flex justify-center border-t px-2 py-1.5">
        <PalettePicker />
      </div>
      <div className="flex items-center justify-between gap-2 border-t p-3 text-xs text-muted-foreground">
        {authEnabled && user ? (
          <>
            <span className="min-w-0 truncate" title={user.email}>
              {user.name}
            </span>
            <div className="flex items-center gap-1.5">
              <Button variant="outline" size="xs" onClick={signOut}>
                <LogOut className="h-3.5 w-3.5" /> Sign out
              </Button>
              <ThemeToggle />
            </div>
          </>
        ) : (
          <>
            <span>Admin · login is off</span>
            <ThemeToggle />
          </>
        )}
      </div>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

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
                Admin
              </span>
            </div>
            <div className="text-[0.625rem] text-muted-foreground">
              Nothing ships without a green light.
            </div>
          </div>
        </Link>

        <TrainingModeIndicator pathname={pathname} />

        <span className="mx-4 mb-2 w-fit rounded-full bg-tertiary px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wider text-tertiary-foreground">
          admin · :3001
        </span>

        <nav className="flex flex-1 flex-col gap-0.5 px-2.5 pt-1">
          <div className="px-2 pb-1 text-[0.625rem] font-semibold uppercase tracking-wider text-muted-foreground">
            Menu
          </div>
          {NAV.map((item) => {
            const active = pathname.startsWith(item.href);
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
        </nav>

        <SidebarFooter />
      </aside>

      <main className="h-screen min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[84rem] px-6 pb-12 pt-5">{children}</div>
      </main>
    </div>
  );
}

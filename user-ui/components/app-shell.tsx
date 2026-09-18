"use client";

/** The sidebar and page frame shared by every screen. */

import {
  ExternalLink,
  FileText,
  FolderGit2,
  LayoutList,
  Moon,
  Plus,
  ShieldCheck,
  Sun,
  BarChart3,
} from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

/**
 * Where the admin console lives. A separate app on its own port (ADR-008 keeps both
 * loginless in v1), so this is a plain external link rather than a route. Overridable
 * because the port is the developer default, not the deployed URL.
 */
const ADMIN_URL = process.env.NEXT_PUBLIC_ADMIN_URL ?? "http://localhost:3001";

const NAV: NavItem[] = [
  { href: "/runs", label: "Runs", icon: LayoutList },
  { href: "/runs/new", label: "New run", icon: Plus },
  { href: "/configs", label: "Config history", icon: FolderGit2 },
];

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

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 flex-shrink-0 flex-col border-r bg-card">
        <div className="flex items-center gap-2.5 p-4">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary text-primary-foreground">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="text-lg font-bold leading-tight tracking-tight">vigilAI</div>
            <div className="text-[0.8125rem] font-medium">QC Validation</div>
            <div className="text-[0.625rem] text-muted-foreground">Fulfillment QC · user-ui</div>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 px-2.5 pt-2">
          <div className="px-2 pb-1 text-[0.625rem] font-semibold uppercase tracking-wider text-muted-foreground">
            Menu
          </div>
          {NAV.map((item) => {
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
        </nav>

        <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            user-ui :3000
          </span>
          <ThemeToggle />
        </div>
      </aside>

      <main className="h-screen min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[84rem] px-6 pb-12 pt-5">{children}</div>
      </main>
    </div>
  );
}

export { BarChart3 };

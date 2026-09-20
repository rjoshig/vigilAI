"use client";

/**
 * What an administrator has to say, at the top of the page (Phase 6.14g).
 *
 * "Maintenance starts at 11pm on the 6th." The tool cannot know that, nobody should
 * have to deploy to say it, and an email is read by whoever happens to open it.
 *
 * Nothing here is dismissible. A notice somebody scheduled is a notice they wanted
 * seen, and a dismiss button turns "read this" into "click this". It takes itself down
 * instead: every notice carries an end, and the server only ever returns the ones in
 * force right now.
 *
 * Polled rather than pushed, on the same interval as the appearance answer, so a
 * notice reaches a tab that has been open all afternoon.
 */

import { AlertTriangle, Info, OctagonAlert } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/** How often an open tab re-reads the notices. */
const POLL_MS = 60_000;

interface Notice {
  id: number;
  level: "info" | "warning" | "critical";
  message: string;
}

const STYLE: Record<Notice["level"], { icon: typeof Info; className: string; label: string }> = {
  info: {
    icon: Info,
    className: "border-info/40 bg-info/10 text-foreground",
    label: "Notice",
  },
  warning: {
    icon: AlertTriangle,
    className: "border-warn/50 bg-warn/15 text-foreground",
    label: "Warning",
  },
  critical: {
    icon: OctagonAlert,
    className: "border-destructive/50 bg-destructive/15 text-foreground",
    label: "Important",
  },
};

export function NoticeBar({ audience }: { audience: "user" | "admin" }) {
  const [notices, setNotices] = React.useState<Notice[]>([]);

  React.useEffect(() => {
    let cancelled = false;

    async function read() {
      try {
        const response = await fetch(`/api/v1/notices?audience=${audience}`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const body = (await response.json()) as Notice[];
        if (!cancelled) setNotices(body);
      } catch {
        // An unreachable API is the page's problem to report, not the banner's. A
        // notice that cannot be read is better absent than replaced by an error.
      }
    }

    void read();
    const timer = setInterval(() => void read(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [audience]);

  if (notices.length === 0) return null;

  return (
    <div className="mb-4 grid gap-2" role="region" aria-label="Notices">
      {notices.map((notice) => {
        const style = STYLE[notice.level] ?? STYLE.info;
        const Icon = style.icon;
        return (
          <div
            key={notice.id}
            role={notice.level === "critical" ? "alert" : "status"}
            className={cn(
              "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
              style.className
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p className="whitespace-pre-wrap">
              <span className="sr-only">{style.label}: </span>
              {notice.message}
            </p>
          </div>
        );
      })}
    </div>
  );
}

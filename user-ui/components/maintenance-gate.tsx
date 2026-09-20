"use client";

/**
 * The maintenance page, shown instead of the app (Phase 6.14j).
 *
 * An administrator switches this on before taking the model endpoint or the database
 * down. Showing a page that says so is the difference between a planned window and a
 * tool that appears broken — a blank screen or a failed upload teaches people the tool
 * is unreliable, and that impression outlasts the maintenance by months.
 *
 * Only the user app does this. The console deliberately ignores the switch: one you
 * cannot reach to turn off is one that strands you.
 *
 * It polls, so the app comes back on its own. Nobody has to be told to refresh.
 */

import { Wrench } from "lucide-react";
import * as React from "react";

import { Logo } from "@/components/logo";
import { usePalette } from "@/components/palette-provider";

export function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const { maintenance, unavailableMessage } = usePalette();

  if (!maintenance) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-5 w-fit">
          <Logo />
        </div>
        <div className="rounded-lg border border-border bg-card p-6">
          <Wrench className="mx-auto mb-3 h-6 w-6 text-muted-foreground" aria-hidden />
          <h1 className="mb-2 text-lg font-semibold">Back shortly</h1>
          <p className="text-sm text-muted-foreground">
            {unavailableMessage ||
              "Greenlight AI is briefly unavailable for maintenance. Runs already submitted are safe and will continue when it returns."}
          </p>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          This page checks for itself every minute; it will come back on its own.
        </p>
      </div>
    </div>
  );
}

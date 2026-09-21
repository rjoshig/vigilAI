"use client";

/**
 * What the deployment has spent (Phase 6.21d).
 *
 * The tool has counted tokens since Phase 2 and nobody could ever see what they cost.
 * This is that, and nothing more: it refuses nothing, gates nothing, and stops nothing.
 * The per-run token budget stays the only hard stop in the product, so the band below
 * produces a warning an administrator reads rather than a delivery that does not run.
 *
 * With no rate configured the screen shows tokens and no currency at all. A cost built
 * on a rate nobody supplied is a number that gets quoted back as fact, so the absence
 * is deliberate and is stated rather than left as a zero.
 */

import { AlertTriangle, Coins } from "lucide-react";
import * as React from "react";

import { Sparkline } from "@/components/sparkline";
import { Badge } from "@/components/ui/primitives";
import type { Spend } from "@/lib/types";
import { cn } from "@/lib/utils";

/** An amount with its currency, in the reader's own locale. */
export function money(amount: number, currency: string): string {
  try {
    return amount.toLocaleString(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: amount < 10 ? 2 : 0,
    });
  } catch {
    // An unrecognised currency code is a typo in a setting, not a reason for a blank
    // screen: show the number and the code somebody typed.
    return `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
  }
}

/** A token count, grouped, so seven figures are readable at a glance. */
function tokens(value: number): string {
  return value.toLocaleString();
}

export function SpendCard({ spend }: { spend: Spend }) {
  const known = spend.rate_per_million > 0;
  const over = spend.monthly_warning > 0 && spend.month_cost > spend.monthly_warning;
  const cacheShare =
    spend.calls + spend.cached_calls > 0
      ? spend.cached_calls / (spend.calls + spend.cached_calls)
      : 0;

  return (
    <section className="rounded-lg border bg-card p-4" data-testid="spend-card">
      <div className="flex items-center gap-2">
        <Coins className="h-4 w-4" />
        <h2 className="text-sm font-semibold">What it cost</h2>
        {known ? null : <Badge tone="muted">no rate set</Badge>}
      </div>

      {known ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <Figure label="This period" value={money(spend.cost, spend.currency)} />
          <Figure
            label="This month"
            value={money(spend.month_cost, spend.currency)}
            tone={over ? "warn" : undefined}
          />
          <Figure label="Tokens sent" value={tokens(spend.tokens)} />
        </div>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Figure label="Tokens sent, this period" value={tokens(spend.tokens)} />
          <Figure label="Tokens sent, this month" value={tokens(spend.month_tokens)} />
        </div>
      )}

      {over ? (
        <p className="mt-3 flex items-start gap-1.5 rounded-md border border-warn/40 bg-warn/5 p-2 text-[0.7rem]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            This month is above the {money(spend.monthly_warning, spend.currency)} you set to be
            warned at. <b>Nothing has been stopped</b> — the only hard limit in the tool is the
            token budget on a single run, which is on the Model settings.
          </span>
        </p>
      ) : null}

      {spend.per_day.length > 1 ? (
        <div className="mt-3">
          <p className="text-[0.7rem] text-muted-foreground">
            {known ? "Cost" : "Tokens"} per day this month
          </p>
          <Sparkline
            values={spend.per_day.map((day) => ({
              day: day.day,
              count: known ? Math.round(day.cost * 100) / 100 : day.tokens,
            }))}
            label={known ? "Cost per day this month" : "Tokens per day this month"}
            tone="tertiary"
          />
        </div>
      ) : null}

      <p className="mt-3 text-[0.7rem] text-muted-foreground">
        {known ? (
          <>
            At {money(spend.rate_per_million, spend.currency)} per million tokens, which was typed
            in rather than measured.{" "}
          </>
        ) : (
          <>Set a cost per million tokens in Settings → Availability to read these as money. </>
        )}
        {spend.cached_calls > 0 ? (
          <>
            {tokens(spend.cached_calls)} of {tokens(spend.calls + spend.cached_calls)} calls (
            {Math.round(cacheShare * 100)}%) were served from the cache and cost nothing; they are
            not in the figures above.
          </>
        ) : null}
      </p>
    </section>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "warn" }) {
  return (
    <div>
      <p className="text-[0.7rem] text-muted-foreground">{label}</p>
      <p className={cn("text-xl font-semibold tabular-nums", tone === "warn" && "text-warn")}>
        {value}
      </p>
    </div>
  );
}

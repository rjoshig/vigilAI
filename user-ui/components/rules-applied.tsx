"use client";

/**
 * The rules that touched this run, grouped by where they came from (Phase 6.13b).
 *
 * A reviewer could see a finding and not that a colleague's observation produced the
 * rule behind it. This names every rule that produced a visible finding, and names the
 * rules that ran in shadow — nothing more about those, because their findings are the
 * administrator's to judge (ADR-040).
 */

import { ChevronDown, ChevronRight, Scale } from "lucide-react";
import * as React from "react";

import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { ORIGIN_LABEL } from "@/lib/display";
import type { RunRules } from "@/lib/types";

export function RulesApplied({ runId }: { runId: number }) {
  const [rules, setRules] = React.useState<RunRules | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    api
      .getRunRules(runId)
      .then(setRules)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.detail : "Could not list the rules.")
      );
  }, [runId]);

  const applied = rules?.applied ?? [];
  const silent = rules?.running_silently ?? [];
  if (!error && rules && applied.length === 0 && silent.length === 0) return null;

  return (
    <Card className="mb-4" data-testid="rules-applied">
      <CardContent className="p-3 text-xs">
        <button
          type="button"
          className="flex w-full items-center gap-1.5 text-left font-semibold"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          <Scale className="h-3.5 w-3.5" /> Rules applied to this run
          {rules ? (
            <span className="ml-auto font-normal text-muted-foreground">
              {applied.length} produced findings
              {silent.length > 0 ? ` · ${silent.length} running silently` : ""}
            </span>
          ) : null}
        </button>

        {open ? (
          error ? (
            <p className="mt-2 text-destructive">{error}</p>
          ) : (
            <div className="mt-2 space-y-2">
              {applied.length > 0 ? (
                <ul className="space-y-1">
                  {applied.map((rule) => (
                    <li key={rule.rule_ref} className="flex flex-wrap items-center gap-2">
                      <Badge tone={rule.origin === "learned" ? "info" : "outline"}>
                        {ORIGIN_LABEL[rule.origin] ?? rule.origin}
                      </Badge>
                      <span className="font-medium">{rule.name}</span>
                      <span className="mono text-muted-foreground">{rule.summary}</span>
                      <span className="ml-auto text-muted-foreground">
                        {rule.findings} finding{rule.findings === 1 ? "" : "s"}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">
                  Every finding on this run came from the OSL and the configuration alone.
                </p>
              )}
              {silent.length > 0 ? (
                <div>
                  <p className="mb-1 text-muted-foreground">
                    Running silently — in shadow, findings counted for the administrator and shown
                    to nobody:
                  </p>
                  <ul className="space-y-0.5">
                    {silent.map((rule) => (
                      <li key={rule.rule_ref} className="flex flex-wrap items-center gap-2">
                        <Badge tone="muted">{ORIGIN_LABEL[rule.origin] ?? rule.origin}</Badge>
                        <span>{rule.name}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}

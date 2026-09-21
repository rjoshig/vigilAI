"use client";

/**
 * What changed since the previous finalized run of the same configuration (ADR-030).
 *
 * Compared by code from what is already stored; the model is not involved. Shown on
 * the review screen so the first question on a repeat delivery, "what is different
 * from last time", has an answer before the findings are read.
 */

import { Explain } from "@/components/explain";
import { GitCompareArrows } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Drift, DriftFinding } from "@/lib/types";

interface DriftCardProps {
  runId: number;
}

function FindingList({ items }: { items: DriftFinding[] }) {
  return (
    <ul className="mt-1 space-y-0.5 pl-1">
      {items.map((item) => (
        <li key={`${item.finding_id}-${item.title}`} className="flex items-start gap-2">
          <span className="mono shrink-0 text-muted-foreground">{item.finding_id}</span>
          <Badge
            tone={
              item.severity === "high"
                ? "destructive"
                : item.severity === "medium"
                  ? "warn"
                  : "muted"
            }
          >
            {item.severity}
          </Badge>
          <span>{item.title}</span>
        </li>
      ))}
    </ul>
  );
}

export function DriftCard({ runId }: DriftCardProps) {
  const [drift, setDrift] = React.useState<Drift | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    api
      .getDrift(runId)
      .then((loaded) => {
        if (!cancelled) setDrift(loaded);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(
            caught instanceof ApiError ? caught.detail : "Could not compare with the previous run."
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (error) return null;
  if (!drift) return <Skeleton className="mb-4 h-12" />;

  const nothingChanged =
    drift.new.length === 0 &&
    drift.resolved.length === 0 &&
    drift.requirements.length === 0 &&
    drift.config.length === 0 &&
    drift.record_layout.length === 0;

  return (
    <Card className="mb-4" data-testid="drift-card">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          <GitCompareArrows className="h-4 w-4" /> Since the previous run
          <Explain label="What is this compared against?">
            <p>
              The previous <b>finalized</b> run of the same configuration for the same customer. Not
              the last run you submitted: a run somebody abandoned, or one still waiting for a
              reviewer, has not been agreed to be a normal delivery, and comparing against one would
              make whatever went wrong in it the new normal.
            </p>
            <p className="mt-2">
              Everything here is a comparison in code. No AI was involved, and nothing here is a
              finding on its own — it is context for the findings above.
            </p>
          </Explain>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-3 text-xs">
        {!drift.previous_run_id ? (
          <p className="text-muted-foreground">{drift.reason}</p>
        ) : (
          <>
            <p className="mb-2 text-muted-foreground">
              Compared with run{" "}
              <span className="mono">VR-{String(drift.previous_run_id).padStart(4, "0")}</span>
              {drift.previous_finished_at ? ` (${drift.previous_finished_at.slice(0, 10)})` : ""}
              {drift.previous_verdict
                ? `, verdict ${drift.previous_verdict.replace("_", " ")}`
                : ""}
              {drift.previous_config_version && drift.config_version
                ? `; configuration v${drift.previous_config_version} → v${drift.config_version}`
                : ""}
              . Compared by code; the model is not involved.
            </p>

            {drift.carried_not_ok.length > 0 ? (
              <div className="mb-2 rounded-md border border-destructive/40 bg-destructive/5 p-2">
                <b>
                  {drift.carried_not_ok.length} Not OK item
                  {drift.carried_not_ok.length === 1 ? "" : "s"} from last time{" "}
                  {drift.carried_not_ok.length === 1 ? "is" : "are"} back.
                </b>{" "}
                The previous reviewer marked these Not OK and this delivery still has them.
                <FindingList items={drift.carried_not_ok} />
              </div>
            ) : null}

            {nothingChanged ? (
              <p className="text-muted-foreground">
                Nothing changed: same findings, same requirements, same configuration, same record
                layout.
              </p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                <div>
                  <b>
                    {drift.new.length} new finding{drift.new.length === 1 ? "" : "s"}
                  </b>
                  {drift.new.length > 0 ? <FindingList items={drift.new} /> : null}
                </div>
                <div>
                  <b>{drift.resolved.length} resolved</b>
                  {drift.resolved.length > 0 ? <FindingList items={drift.resolved} /> : null}
                </div>
                {drift.requirements.length > 0 ? (
                  <details className="sm:col-span-2">
                    <summary className="cursor-pointer font-semibold">
                      {drift.requirements.length} requirement
                      {drift.requirements.length === 1 ? "" : "s"} changed
                    </summary>
                    <ul className="mt-1 space-y-0.5 pl-1">
                      {drift.requirements.map((item) => (
                        <li key={`${item.source_ref}-${item.change}`}>
                          <span className="mono">{item.source_ref}</span> · {item.req_type} ·{" "}
                          <Badge tone="muted">{item.change}</Badge>{" "}
                          {item.change === "changed"
                            ? `${item.before} → ${item.after}`
                            : item.after || item.before}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                {drift.record_layout.length > 0 ? (
                  <details className="sm:col-span-2">
                    <summary className="cursor-pointer font-semibold">
                      {drift.record_layout.length} record layout change
                      {drift.record_layout.length === 1 ? "" : "s"}
                    </summary>
                    <p className="mt-1 text-muted-foreground">
                      The shape of the delivered file itself. A field that was ten characters and is
                      now nine will not show up in any finding above, and is exactly the kind of
                      change a customer notices first.
                    </p>
                    <ul className="mt-1 space-y-0.5 pl-1">
                      {drift.record_layout.map((item) => (
                        <li key={`${item.name}-${item.change}`}>
                          <span className="mono">{item.name}</span>{" "}
                          <Badge tone={item.change === "removed" ? "warn" : "muted"}>
                            {item.change}
                          </Badge>{" "}
                          <span className="mono">
                            {item.before && item.after
                              ? `${item.before} → ${item.after}`
                              : item.after || item.before}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                {drift.config.length > 0 ? (
                  <details className="sm:col-span-2">
                    <summary className="cursor-pointer font-semibold">
                      {drift.config.length} configuration path{drift.config.length === 1 ? "" : "s"}{" "}
                      changed
                    </summary>
                    <ul className="mt-1 space-y-0.5 pl-1">
                      {drift.config.map((item) => (
                        <li key={item.path}>
                          <span className="mono">{item.path}</span>{" "}
                          <Badge tone="muted">{item.change}</Badge>{" "}
                          <span className="mono">
                            {item.change === "changed"
                              ? `${item.before} → ${item.after}`
                              : item.after || item.before}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

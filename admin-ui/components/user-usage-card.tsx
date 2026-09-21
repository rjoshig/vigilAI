"use client";

/**
 * Who is using the tool, and who is having a hard time with it (Phase 6.19).
 *
 * The dashboard above this counts the deployment. That answers *is anybody using it*
 * and nothing else. The question an administrator usually arrives with is narrower —
 * **is this going badly for a particular group of people?** — and a single failure rate
 * cannot answer it.
 *
 * Three columns carry most of that, and they are kept apart because they have different
 * causes and different fixes:
 *
 * - **Failed** — the pipeline raised. Usually the tool's problem.
 * - **Held** — what was uploaded disagreed with what was typed (ADR-041). Usually a
 *   person's problem, and the most teachable of the three.
 * - **Re-runs** — the same order submitted again. Something was wrong either way.
 *
 * A rate is shown against the deployment's own average rather than a threshold somebody
 * invented: *twice everyone else* is a fact an administrator can act on, and a score out
 * of a hundred is not. Rows under a handful of runs are not flagged at all, because a
 * rate over three runs is noise whatever it says.
 */

import { ChevronLeft, ChevronRight, Download, ExternalLink, Users } from "lucide-react";
import * as React from "react";

import { Explain, FieldEffect } from "@/components/explain";
import { Sparkline } from "@/components/sparkline";
import { money } from "@/components/spend-card";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { UsageByUser, UserUsage } from "@/lib/types";
import { cn, fmtInt } from "@/lib/utils";

/** Where the user app lives, so a count can open the runs behind it. */
const USER_URL = process.env.NEXT_PUBLIC_USER_URL ?? "http://localhost:3000";

/** Below this many runs a rate is noise, so nothing is flagged against the average. */
const MIN_RUNS_TO_COMPARE = 5;

/** How far above the deployment average a rate has to be before it is worth saying. */
const NOTABLE_MULTIPLE = 1.5;

/** Rows per page. Enough to compare people against each other without scrolling. */
const PAGE_SIZE = 10;

/**
 * The columns a downloaded file carries, in order.
 *
 * Deliberately wider than the table: a spreadsheet is where somebody builds the report
 * they were asked for, so it gets the counts the screen leaves as a tooltip. The header
 * is written in words rather than field names, because the file is read by people who
 * have never seen this code.
 */
const CSV_COLUMNS: { header: string; value: (row: UserUsage) => string | number }[] = [
  { header: "Person", value: (row) => row.name },
  { header: "Username", value: (row) => row.username },
  { header: "Roles", value: (row) => (row.roles ?? []).join(" + ") },
  { header: "Account active", value: (row) => (row.is_active ? "yes" : "no") },
  { header: "Runs", value: (row) => row.runs },
  { header: "Distinct orders", value: (row) => row.orders },
  { header: "Customers", value: (row) => row.customers },
  { header: "Configurations", value: (row) => row.configurations },
  { header: "Signed off", value: (row) => row.finalized },
  { header: "Awaiting review", value: (row) => row.needs_review },
  { header: "In flight", value: (row) => row.in_flight },
  { header: "Cancelled", value: (row) => row.cancelled },
  { header: "Failed", value: (row) => row.failed },
  { header: "Held", value: (row) => row.held },
  { header: "Re-runs", value: (row) => row.repeat_runs },
  { header: "Runs with an artifact mismatch", value: (row) => row.mismatch_runs },
  { header: "Failure rate", value: (row) => row.failure_rate },
  { header: "Held rate", value: (row) => row.held_rate },
  { header: "Re-run rate", value: (row) => row.repeat_rate },
  { header: "High findings", value: (row) => row.high_findings },
  { header: "Completed runs", value: (row) => row.completed_runs },
  { header: "High findings per completed run", value: (row) => row.high_per_run },
  { header: "Tokens sent", value: (row) => row.tokens },
  { header: "Cost", value: (row) => row.cost },
  { header: "Calls served from the cache", value: (row) => row.cached_calls },
  { header: "First run", value: (row) => row.first_run_at ?? "" },
  { header: "Last run", value: (row) => row.last_run_at ?? "" },
];

/**
 * One CSV cell, quoted where it has to be.
 *
 * A customer or a person's name can contain a comma, and a file that splits on one is
 * worse than no file: it is wrong in a way nobody notices until a column is read as a
 * name it is not.
 */
function cell(value: string | number): string {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * The whole period as a spreadsheet.
 *
 * Every person in the period, not the page on screen: somebody downloading is doing
 * something with all of it, and a file that quietly held ten rows would be the sort of
 * error that survives into a report.
 *
 * @param usage The period as the API returned it.
 * @returns The file's contents.
 */
export function toCsv(usage: UsageByUser): string {
  const lines = [
    CSV_COLUMNS.map((column) => cell(column.header)).join(","),
    ...usage.users.map((row) => CSV_COLUMNS.map((column) => cell(column.value(row))).join(",")),
  ];
  // The averages the rates are read against, so the file is not missing the thing that
  // makes a rate mean something.
  lines.push("");
  lines.push(
    cell(`Across everybody, ${usage.start} to ${usage.end}`) +
      `,${usage.runs} runs,failure rate ${usage.failure_rate},held rate ${usage.held_rate},re-run rate ${usage.repeat_rate}`
  );
  return lines.join("\n");
}

/** What the downloaded file is called, so a folder of them stays sortable. */
export function csvFilename(usage: UsageByUser): string {
  return `usage-by-person-${usage.start}-to-${usage.end}.csv`;
}

/** Hand the file to the browser. */
function download(usage: UsageByUser): void {
  const blob = new Blob([toCsv(usage)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = csvFilename(usage);
  anchor.click();
  URL.revokeObjectURL(url);
}

function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(0)}%`;
}

/** What each period is called in the picker. */
const PERIOD_LABELS: Record<number, string> = {
  7: "7 days",
  30: "30 days",
  90: "3 months",
  180: "6 months",
};

export function UserUsageCard({ onError }: { onError: (message: string) => void }) {
  const [days, setDays] = React.useState(30);
  const [usage, setUsage] = React.useState<UsageByUser | null>(null);
  const [page, setPage] = React.useState(0);

  const load = React.useCallback(
    async (period: number) => {
      try {
        setUsage(await api.getUsageByUser(period));
      } catch (caught) {
        onError(caught instanceof ApiError ? caught.detail : "Could not count runs by person.");
      }
    },
    [onError]
  );

  React.useEffect(() => {
    // Back to the first page whenever the period changes: page 4 of the last period is
    // not a place anybody meant to be.
    setPage(0);
    void load(days);
  }, [days, load]);

  const periods = usage?.periods ?? [7, 30, 90, 180];
  const people = usage?.users ?? [];
  const pages = Math.max(1, Math.ceil(people.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = people.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-1">
          <Users className="h-4 w-4 text-muted-foreground" aria-hidden />
          Who is using it
          <Explain label="What this table is for">
            One row per person who submitted something in the period, busiest first.
            <br />
            <br />
            <b>The three failure columns are separate on purpose.</b> <i>Failed</i> means the
            pipeline raised — usually the tool&rsquo;s problem. <i>Held</i> means the files
            disagreed with the form — usually something a person can be shown how to avoid.{" "}
            <i>Re-runs</i> means the same order came back. Lumping them into one number hides which
            of the three you can do anything about.
            <br />
            <br />
            <b>Rates are compared with this deployment&rsquo;s own average</b>, not a threshold we
            invented, and a row with fewer than {MIN_RUNS_TO_COMPARE} runs is never flagged — over
            three runs a rate says nothing.
            <br />
            <br />
            Click any count to open those runs.
          </Explain>
          <span className="ml-auto flex flex-wrap items-center gap-1">
            {usage && usage.users.length > 0 ? (
              <Button
                size="xs"
                variant="outline"
                className="mr-1"
                onClick={() => download(usage)}
                title="Every person in the period, not just this page"
              >
                <Download className="h-3 w-3" /> CSV
              </Button>
            ) : null}
            {periods.map((period) => (
              <Button
                key={period}
                size="xs"
                variant={period === days ? "default" : "outline"}
                onClick={() => setDays(period)}
              >
                {PERIOD_LABELS[period] ?? `${period} days`}
              </Button>
            ))}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!usage ? (
          <Skeleton className="h-40" />
        ) : usage.users.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">
            Nobody submitted a run between {usage.start} and {usage.end}.
          </p>
        ) : (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              {fmtInt(usage.runs)} runs by {usage.users.length}{" "}
              {usage.users.length === 1 ? "person" : "people"}, {usage.start} to {usage.end}. Across
              everybody: {percent(usage.failure_rate)} failed, {percent(usage.held_rate)} held,{" "}
              {percent(usage.repeat_rate)} re-run.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-1 pr-2 font-medium">Person</th>
                    <th className="py-1 pr-2 font-medium">Runs</th>
                    <th className="py-1 pr-2 font-medium">Orders</th>
                    <th className="py-1 pr-2 font-medium">Signed off</th>
                    <th className="py-1 pr-2 font-medium">To review</th>
                    <th className="py-1 pr-2 font-medium">Failed</th>
                    <th className="py-1 pr-2 font-medium">Held</th>
                    <th className="py-1 pr-2 font-medium">Re-runs</th>
                    <th className="py-1 pr-2 font-medium">High / run</th>
                    <th className="py-1 pr-2 font-medium">
                      {usage.rate_per_million > 0 ? "Cost" : "Tokens"}
                    </th>
                    <th className="py-1 pr-2 font-medium">Last run</th>
                    <th className="py-1 font-medium">Per day</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row) => (
                    <Row key={row.user_id} row={row} deployment={usage} />
                  ))}
                </tbody>
              </table>
            </div>
            {pages > 1 ? (
              <div className="mt-3 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {current * PAGE_SIZE + 1}–{current * PAGE_SIZE + shown.length} of {people.length},
                  busiest first
                </span>
                <span className="flex items-center gap-1">
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={current === 0}
                    onClick={() => setPage(current - 1)}
                  >
                    <ChevronLeft className="h-3 w-3" /> Previous
                  </Button>
                  <span className="px-1 text-muted-foreground">
                    Page {current + 1} of {pages}
                  </span>
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={current >= pages - 1}
                    onClick={() => setPage(current + 1)}
                  >
                    Next <ChevronRight className="h-3 w-3" />
                  </Button>
                </span>
              </div>
            ) : null}
            <FieldEffect
              kind="code"
              className="mt-3"
              note="Counted by code from the run records. No model is involved, and nothing here is an opinion about a person — it is what happened to the runs they submitted."
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** One person's row, with a link behind every count. */
function Row({ row, deployment }: { row: UserUsage; deployment: UsageByUser }) {
  const comparable = row.runs >= MIN_RUNS_TO_COMPARE;
  // Money only where somebody has set a rate. A cost built on a rate nobody
  // supplied is a number that gets quoted back as fact (Phase 6.21d).
  const costed = deployment.rate_per_million > 0;
  const currency = deployment.currency;

  return (
    <tr className="border-b last:border-0">
      <td className="py-1.5 pr-2">
        <span className="font-medium">{row.name}</span>
        {row.username && row.username !== row.name ? (
          <span className="text-muted-foreground"> · {row.username}</span>
        ) : null}
        {!row.is_active ? (
          <Badge tone="muted" className="ml-1">
            closed
          </Badge>
        ) : null}
      </td>
      <Count value={row.runs} userId={row.user_id} />
      <td className="py-1.5 pr-2">{fmtInt(row.orders)}</td>
      <Count value={row.finalized} userId={row.user_id} status="finalized" />
      <Count value={row.needs_review} userId={row.user_id} status="needs_review" />
      <Count
        value={row.failed}
        userId={row.user_id}
        status="failed"
        rate={row.failure_rate}
        average={deployment.failure_rate}
        comparable={comparable}
      />
      <Count
        value={row.held}
        userId={row.user_id}
        status="held"
        rate={row.held_rate}
        average={deployment.held_rate}
        comparable={comparable}
      />
      <td
        className="py-1.5 pr-2"
        title={`${row.repeat_runs} of ${row.runs} runs were another go at an order already counted`}
      >
        {fmtInt(row.repeat_runs)}
      </td>
      <td className="py-1.5 pr-2" title={`${row.high_findings} across ${row.completed_runs} runs`}>
        {row.high_per_run.toFixed(1)}
      </td>
      <td
        className="py-1.5 pr-2 tabular-nums"
        title={
          row.cached_calls > 0
            ? `${fmtInt(row.tokens)} tokens sent; ${fmtInt(row.cached_calls)} calls came from the cache and cost nothing`
            : `${fmtInt(row.tokens)} tokens sent`
        }
      >
        {costed ? money(row.cost, currency) : fmtInt(row.tokens)}
      </td>
      <td className="py-1.5 pr-2 text-muted-foreground">
        {row.last_run_at ? row.last_run_at.slice(0, 10) : "—"}
      </td>
      <td className="w-32 py-1.5">
        <Sparkline values={row.per_day} label={`Runs per day by ${row.name}`} tone="tertiary" />
      </td>
    </tr>
  );
}

/**
 * A count that opens the runs behind it, flagged when it is well above average.
 *
 * Zero is not a link: there is nothing to open, and a link that lands on an empty list
 * reads as a fault in the console.
 */
function Count({
  value,
  userId,
  status,
  rate,
  average,
  comparable,
}: {
  value: number;
  userId: number;
  status?: string;
  rate?: number;
  average?: number;
  comparable?: boolean;
}) {
  const notable =
    comparable &&
    rate !== undefined &&
    average !== undefined &&
    average > 0 &&
    rate >= average * NOTABLE_MULTIPLE;

  const href = `${USER_URL}/runs?submitted_by=${userId}${status ? `&status=${status}` : ""}`;

  return (
    <td className={cn("py-1.5 pr-2", notable && "font-semibold text-destructive")}>
      {value === 0 ? (
        <span className="text-muted-foreground">0</span>
      ) : (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
          title={
            notable
              ? `${percent(rate ?? 0)} of their runs, against ${percent(average ?? 0)} across everybody`
              : "Open these runs"
          }
        >
          {fmtInt(value)}
          <ExternalLink className="h-2.5 w-2.5 opacity-50" aria-hidden />
        </a>
      )}
      {notable ? <span className="ml-1 text-[0.65rem]">▲</span> : null}
    </td>
  );
}

"use client";

/**
 * What the tool displaced, over a period somebody chooses (Phase 6.16).
 *
 * An administrator is asked periodically what the tool has been worth. The numbers are
 * already in the run tables; this is the arithmetic and somewhere to put it.
 *
 * Two things this deliberately does not do:
 *
 * - **It does not count runs.** An order checked three times displaced one manual
 *   check, not three. A figure that flatters is one nobody outside the team believes,
 *   so the repeat count is shown beside the order count rather than absorbed into it.
 * - **It does not pretend the hours are measured.** The tool cannot know how long a
 *   manual check takes; an administrator sets it. The report says so on its face, so a
 *   reader can disagree with the assumption rather than with the arithmetic.
 *
 * Printing is the browser's, not a second renderer: the layout has a print stylesheet
 * and `window.print()` produces the PDF. One less thing to keep in step with the
 * screen, and it works wherever the console does.
 */

import { CalendarRange, Printer } from "lucide-react";
import * as React from "react";

import { Explain, FieldEffect } from "@/components/explain";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ValueReport } from "@/lib/types";

/** An ISO date this many days ago, for the default period. */
function daysAgo(days: number): string {
  const at = new Date();
  at.setDate(at.getDate() - days);
  return at.toISOString().slice(0, 10);
}

export function ValueReportCard({ onError }: { onError: (message: string) => void }) {
  const [start, setStart] = React.useState(daysAgo(30));
  const [end, setEnd] = React.useState(new Date().toISOString().slice(0, 10));
  const [report, setReport] = React.useState<ValueReport | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function generate() {
    setBusy(true);
    try {
      setReport(await api.getValueReport(start, end));
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : "Could not build the report.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="value-report">
      <CardHeader>
        <CardTitle className="flex items-center gap-1">
          <CalendarRange className="h-4 w-4 text-muted-foreground" aria-hidden />
          What this has displaced
          <Explain label="What this report is and is not">
            Distinct orders finalized in the period, multiplied by the hours you say a manual check
            takes.
            <br />
            <br />
            <b>Orders, not runs.</b> An order checked three times displaced one manual check. The
            repeat count is shown separately rather than folded in, because a figure that flatters
            is one nobody outside the team will believe.
            <br />
            <br />
            <b>The hours are yours.</b> The tool cannot measure how long a manual check takes. Set
            it under Settings → Availability; the report prints the figure it used so a reader can
            argue with the assumption rather than the arithmetic.
          </Explain>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="no-print mb-4 flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="vr-start">From</Label>
            <Input
              id="vr-start"
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="vr-end">To</Label>
            <Input
              id="vr-end"
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
            />
          </div>
          <Button disabled={busy} onClick={() => void generate()}>
            {busy ? "Counting…" : "Generate"}
          </Button>
          {report ? (
            <Button variant="outline" onClick={() => window.print()}>
              <Printer className="mr-1 h-4 w-4" aria-hidden />
              Save as PDF
            </Button>
          ) : null}
        </div>

        {report ? (
          <div className="rounded-md border border-border p-4">
            <h3 className="text-base font-semibold">
              QC validation, {report.start} to {report.end}
            </h3>
            <p className="mb-4 text-xs text-muted-foreground">
              {report.days} days · counted from the run records
            </p>

            <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Figure label="Orders validated" value={report.orders} />
              <Figure label="Runs" value={report.runs} hint={`${report.repeat_runs} re-runs`} />
              <Figure label="Customers" value={report.customers} />
              <Figure
                label="Manual hours displaced"
                value={report.hours_saved}
                hint={`about ${report.working_weeks} working weeks`}
                emphasis
              />
            </div>

            <p className="text-xs text-muted-foreground">
              Orders are counted once however many times they were run: {report.runs} runs covered{" "}
              {report.orders} distinct orders. Hours are {report.orders} orders ×{" "}
              <b>{report.hours_per_order} hours</b>, which is the figure this deployment was
              configured with rather than one the tool measured. Only finalized runs are counted;
              work still in review has not displaced anything yet.
            </p>
          </div>
        ) : (
          <FieldEffect
            kind="code"
            note="Counted by code from the run records. No model is involved, and the only figure not counted is the hours-per-order you set."
          />
        )}
      </CardContent>
    </Card>
  );
}

function Figure({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string;
  value: number;
  hint?: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div className={emphasis ? "text-2xl font-semibold text-primary" : "text-2xl font-semibold"}>
        {value.toLocaleString()}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
      {hint ? <div className="text-[0.7rem] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

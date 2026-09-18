"use client";

/**
 * The final report screen: view the frozen page, download the PDF, clone the run.
 *
 * The report is shown in an iframe of the stored file rather than re-rendered here.
 * It is self-contained by design, and re-implementing it in React would give two
 * versions of the same document that could drift apart (ADR-005).
 */

import { Copy, Download, ExternalLink, Lock } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  ErrorState,
  PageHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { RunDetail } from "@/lib/types";

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const runId = Number(params.id);

  const [run, setRun] = React.useState<RunDetail | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setRun(await api.getRun(runId));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [runId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function finalize() {
    setBusy(true);
    try {
      await api.finalize(runId);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not generate the final report.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !run) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!run) return <Skeleton className="h-96" />;

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            <Link href="/runs" className="hover:underline">
              Runs
            </Link>{" "}
            ›{" "}
            <Link href={`/runs/${runId}`} className="mono hover:underline">
              VR-{String(runId).padStart(4, "0")}
            </Link>
          </>
        }
        title="Final report"
        description={`${run.customer_name} · ${run.order_number} · configuration ${run.configuration_id}`}
        action={
          run.finalized ? (
            <>
              <Badge tone="muted">
                <Lock className="h-3 w-3" /> frozen
              </Badge>
              <a href={api.reportPdfUrl(runId)} download>
                <Button variant="outline" size="sm">
                  <Download className="h-4 w-4" /> Download PDF
                </Button>
              </a>
              <a href={api.reportUrl(runId)} target="_blank" rel="noreferrer">
                <Button variant="outline" size="sm">
                  <ExternalLink className="h-4 w-4" /> Open in a tab
                </Button>
              </a>
              <Button
                size="sm"
                onClick={async () => {
                  const result = await api.cloneRun(runId);
                  router.push(`/runs/${result.run_id}`);
                }}
              >
                <Copy className="h-4 w-4" /> Clone run
              </Button>
            </>
          ) : null
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} />
        </div>
      ) : null}

      {!run.finalized ? (
        <Card>
          <CardContent className="flex flex-col items-start gap-3 p-6">
            <h2 className="text-base font-semibold">This run has not been finalized</h2>
            <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground">
              The report is generated once from the reviewed findings, stored, and never
              regenerated. Every high-severity finding needs a decision first.
              {run.can_finalize
                ? " They all have one, so it can be generated now."
                : " Some still do not have one."}
            </p>
            <div className="flex gap-2">
              <Link href={`/runs/${runId}`}>
                <Button variant="outline" size="sm">
                  Back to review
                </Button>
              </Link>
              <Button disabled={!run.can_finalize || busy} onClick={() => void finalize()}>
                <Lock className="h-4 w-4" />
                {busy ? "Generating…" : "Generate final report"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <iframe
            title={`Final report for run ${runId}`}
            src={api.reportUrl(runId)}
            className="h-[calc(100vh-11rem)] w-full border-0 bg-white"
          />
        </Card>
      )}
    </>
  );
}

"use client";

/** Config history: captured configs by configuration ID and version. */

import { Eye } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Skeleton,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ConfigDetail, ConfigSummary } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

export default function ConfigsPage() {
  const [configs, setConfigs] = React.useState<ConfigSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");
  const [latestOnly, setLatestOnly] = React.useState(false);
  const [viewing, setViewing] = React.useState<ConfigDetail | null>(null);

  const load = React.useCallback(async () => {
    try {
      setConfigs(await api.listConfigs(latestOnly));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load the configs.");
    }
  }, [latestOnly]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const visible = (configs ?? []).filter((config) => {
    const needle = search.trim().toLowerCase();
    return (
      !needle || `${config.configuration_id} ${config.customer_name}`.toLowerCase().includes(needle)
    );
  });

  return (
    <>
      <PageHeader
        title="Config history"
        description="Captured ETL configs by configuration ID and version. A new version is saved only when the content hash changes, so configs outlive the runs that used them."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="max-w-xs"
          placeholder="Search configuration ID or customer…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search configs"
        />
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={latestOnly}
            onChange={(event) => setLatestOnly(event.target.checked)}
          />
          Latest version only
        </label>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {!configs && !error ? <Skeleton className="h-64" /> : null}

      {configs && !error ? (
        <Card className="p-0">
          {visible.length === 0 ? (
            <EmptyState
              title="No configs captured yet"
              hint="A config is recorded the first time a run uploads it."
            />
          ) : (
            <Table>
              <thead>
                <TR className="hover:bg-transparent">
                  <TH>Configuration ID</TH>
                  <TH>Version</TH>
                  <TH>Customer</TH>
                  <TH>Captured</TH>
                  <TH>Run by</TH>
                  <TH>Last modified (in file)</TH>
                  <TH>SHA-256</TH>
                  <TH className="text-right">Runs</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </thead>
              <tbody>
                {visible.map((config) => (
                  <TR key={config.id}>
                    <TD className="mono">{config.configuration_id}</TD>
                    <TD>
                      <Badge tone="info">v{config.version}</Badge>
                    </TD>
                    <TD>{config.customer_name || "—"}</TD>
                    <TD className="text-xs text-muted-foreground">{fmtTime(config.created_at)}</TD>
                    <TD className="whitespace-nowrap text-xs">{config.created_by || "—"}</TD>
                    <TD className="text-xs text-muted-foreground">{config.last_modified || "—"}</TD>
                    <TD className="mono text-xs">{config.sha256.slice(0, 8)}…</TD>
                    <TD className="text-right tabular-nums">{config.run_count}</TD>
                    <TD className="text-right">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={async () => setViewing(await api.getConfig(config.id))}
                      >
                        <Eye className="h-3.5 w-3.5" /> View
                      </Button>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      ) : null}

      {viewing ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Config content"
          onClick={() => setViewing(null)}
        >
          <Card
            className="max-h-[85vh] w-full max-w-3xl overflow-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <CardHeader className="border-b">
              <CardTitle className="mono">
                {viewing.configuration_id} · v{viewing.version}
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setViewing(null)}>
                Close
              </Button>
            </CardHeader>
            <CardContent className="pt-4">
              <pre className="mono overflow-x-auto rounded-md border bg-muted p-3 text-[0.72rem] leading-relaxed">
                {JSON.stringify(viewing.content, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}

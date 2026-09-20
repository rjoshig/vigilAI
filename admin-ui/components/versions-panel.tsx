"use client";

/**
 * The last ten versions of a definition, with revert (Phase 6.8c, ADR-029).
 *
 * A version is a snapshot taken after every save; a revert writes an old one back
 * as a new version, so the list is also the audit trail. The administrator types
 * `revert` because the change reaches every future run, and the API enforces the
 * same word with a 400.
 */

import { History } from "lucide-react";
import * as React from "react";

import { Badge, Button, Input, Label, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { DefinitionVersion, VersionKind } from "@/lib/types";
import { versionLabel } from "@/lib/versions";

interface VersionsPanelProps {
  kind: VersionKind;
  objectKey: string;
  /** Called after a successful revert so the owner reloads what it shows. */
  onReverted: () => void;
}

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function VersionsPanel({ kind, objectKey, onReverted }: VersionsPanelProps) {
  const [rows, setRows] = React.useState<DefinitionVersion[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState<number | null>(null);
  const [typed, setTyped] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setRows(await api.listVersions(kind, objectKey));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not load the versions.");
    }
  }, [kind, objectKey]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function revert(version: number) {
    setBusy(true);
    try {
      await api.revertVersion(kind, objectKey, version, typed.trim());
      setConfirming(null);
      setTyped("");
      await load();
      onReverted();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not revert.");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (!rows) return <Skeleton className="h-16" />;
  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No versions yet; the first save makes one.</p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5" data-testid={`versions-${kind}-${objectKey}`}>
      <p className="flex items-center gap-1 text-[0.7rem] text-muted-foreground">
        <History className="h-3 w-3" /> The last ten versions, newest first. Reverting restores that
        version as a new one; nothing is lost.
      </p>
      <ul className="divide-y rounded-md border">
        {rows.map((row, index) => (
          <li key={row.version} className="flex flex-wrap items-center gap-2 px-2 py-1.5 text-xs">
            <span className="mono font-semibold">{versionLabel(row.version)}</span>
            {index === 0 ? <Badge tone="success">current</Badge> : null}
            {row.reverted_from ? (
              <Badge tone="muted">from {versionLabel(row.reverted_from)}</Badge>
            ) : null}
            <span className="flex-1">{row.summary || "saved"}</span>
            <span className="text-muted-foreground">
              {row.created_by || "—"} · {when(row.created_at)}
            </span>
            {index === 0 ? null : confirming === row.version ? (
              <span className="flex items-center gap-1.5">
                <Label htmlFor={`revert-${kind}-${objectKey}-${row.version}`}>
                  Type <span className="mono font-semibold">revert</span>
                </Label>
                <Input
                  id={`revert-${kind}-${objectKey}-${row.version}`}
                  className="mono h-7 w-24 text-xs"
                  autoComplete="off"
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                />
                <Button
                  size="xs"
                  disabled={busy || typed.trim() !== "revert"}
                  onClick={() => void revert(row.version)}
                >
                  revert
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => {
                    setConfirming(null);
                    setTyped("");
                  }}
                >
                  Cancel
                </Button>
              </span>
            ) : (
              <Button
                size="xs"
                variant="outline"
                disabled={busy}
                onClick={() => setConfirming(row.version)}
              >
                Revert to {versionLabel(row.version)}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

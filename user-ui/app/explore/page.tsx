"use client";

/**
 * Explore a sample, and point at part of it (Phase 6.1e).
 *
 * An observation is worth far more anchored to the thing the person means than as
 * prose alone. Until now a reviewer could only anchor from a finding, which limited
 * them to what the tool had already noticed — and the most valuable thing a person
 * knows is usually about something the tool said nothing about.
 *
 * So this shows the stored samples read-only: a workbook cell by cell with the label
 * beside each one, an OSL by section, a configuration by JSON path. Clicking any of
 * them opens the observation form already pointing at it.
 *
 * Nothing here changes anything, and values are masked exactly as a real upload is.
 */

import { FileSearch, Lightbulb } from "lucide-react";
import * as React from "react";

import { ObservationDialog, anchorOf, useTrainingEnabled } from "@/components/observation-dialog";
import { TrainAiTag } from "@/components/train-ai-tag";
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
  Select,
  Skeleton,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Anchor, CellPreview, ExploreArtifact, SamplePreview } from "@/lib/types";

/** What a click on a cell means, which depends on what kind of artifact it came from. */
function anchorFor(artifact: ExploreArtifact, sheet: string, cell: CellPreview): Anchor {
  if (artifact.kind === "osl") {
    // An OSL "sheet" is a section and its "cell" a paragraph, which is what the
    // preview endpoint renders it as.
    return anchorOf("osl_section", { reference: cell.label || sheet, value: cell.value });
  }
  if (artifact.kind === "config") {
    return anchorOf("config_path", { reference: cell.label || cell.cell, value: cell.value });
  }
  return anchorOf("report_cell", {
    artifact: artifact.key,
    sheet,
    cell: cell.cell,
    field: cell.label,
    value: cell.value,
  });
}

/** How to describe what was selected, in one line, above the form. */
function contextFor(artifact: ExploreArtifact, sheet: string, cell: CellPreview): string {
  if (artifact.kind === "osl") return `${artifact.label} · ${cell.label || sheet}`;
  if (artifact.kind === "config") return `${artifact.label} · ${cell.label || cell.cell}`;
  return `${artifact.label} · ${sheet}!${cell.cell}${cell.label ? ` (${cell.label})` : ""}`;
}

export default function ExplorePage() {
  const trainingEnabled = useTrainingEnabled();
  const [artifacts, setArtifacts] = React.useState<ExploreArtifact[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<number | null>(null);
  const [preview, setPreview] = React.useState<SamplePreview | null>(null);
  const [loadingPreview, setLoadingPreview] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [pointingAt, setPointingAt] = React.useState<{
    anchors: Anchor[];
    context: string;
  } | null>(null);

  React.useEffect(() => {
    api
      .listSamples()
      .then(setArtifacts)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.detail : "Could not list the samples.")
      );
  }, []);

  const artifact = React.useMemo(
    () =>
      (artifacts ?? []).find((entry) => entry.samples.some((sample) => sample.id === selected)) ??
      null,
    [artifacts, selected]
  );

  React.useEffect(() => {
    if (selected === null) {
      setPreview(null);
      return;
    }
    setLoadingPreview(true);
    api
      .previewSample(selected)
      .then(setPreview)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.detail : "Could not read that sample.")
      )
      .finally(() => setLoadingPreview(false));
  }, [selected]);

  if (error && !artifacts) return <ErrorState message={error} />;
  if (!artifacts) return <Skeleton className="h-96" />;

  const needle = search.trim().toLowerCase();

  return (
    <>
      <PageHeader
        title={<>Explore a sample {trainingEnabled ? <TrainAiTag /> : null}</>}
        description={
          trainingEnabled
            ? "Look at an example of any artifact the tool accepts, and point at the part you want it to check. Values are masked exactly as they are on a real run."
            : "Look at an example of any artifact the tool accepts. Values are masked exactly as they are on a real run."
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} />
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select
          className="max-w-sm"
          aria-label="Choose a sample"
          value={selected ?? ""}
          onChange={(event) => setSelected(event.target.value ? Number(event.target.value) : null)}
        >
          <option value="">Choose a sample…</option>
          {artifacts.map((entry) => (
            <optgroup key={entry.key} label={entry.label}>
              {entry.samples.map((sample) => (
                <option key={sample.id} value={sample.id}>
                  {sample.label || sample.filename}
                  {sample.scope_code ? ` · ${sample.scope_code}` : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </Select>
        {preview ? (
          <Input
            className="max-w-xs"
            placeholder="Search this sample…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search this sample"
          />
        ) : null}
      </div>

      {artifacts.length === 0 ? (
        <EmptyState
          title="No samples yet"
          hint="An administrator uploads an example of each artifact type in the admin console."
        />
      ) : null}

      {loadingPreview ? <Skeleton className="h-64" /> : null}

      {preview && artifact && !loadingPreview
        ? preview.sheets.map((sheet) => {
            const cells = sheet.cells.filter(
              (cell) =>
                !needle || `${cell.cell} ${cell.label} ${cell.value}`.toLowerCase().includes(needle)
            );
            if (cells.length === 0) return null;
            return (
              <Card key={sheet.name} className="mb-4" data-testid="sample-sheet">
                <CardHeader className="border-b">
                  <CardTitle className="flex items-center gap-2">
                    <FileSearch className="h-4 w-4" /> {sheet.name}
                    <Badge tone="muted">{cells.length} shown</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-3">
                  <ul className="flex flex-col gap-1">
                    {cells.map((cell) => (
                      <li
                        key={`${sheet.name}-${cell.cell}`}
                        className="flex flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 text-xs"
                        data-testid="sample-cell"
                      >
                        <span className="mono w-20 shrink-0 text-muted-foreground">
                          {cell.cell}
                        </span>
                        {cell.label ? <span className="font-medium">{cell.label}</span> : null}
                        <span className="min-w-[6rem] flex-1 text-muted-foreground">
                          {cell.value}
                        </span>
                        {trainingEnabled ? (
                          <Button
                            size="xs"
                            variant="ghost"
                            title="Tell the tool what this should be checked against"
                            onClick={() =>
                              setPointingAt({
                                anchors: [anchorFor(artifact, sheet.name, cell)],
                                context: contextFor(artifact, sheet.name, cell),
                              })
                            }
                          >
                            <Lightbulb className="h-3.5 w-3.5" /> What should this check?
                          </Button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            );
          })
        : null}

      {pointingAt ? (
        <ObservationDialog
          anchors={pointingAt.anchors}
          context={pointingAt.context}
          onClose={() => setPointingAt(null)}
        />
      ) : null}
    </>
  );
}

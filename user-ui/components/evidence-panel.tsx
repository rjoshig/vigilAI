"use client";

/**
 * The side panel showing a finding's three-way evidence: the OSL text, the config
 * path and value, and the report cell (`docs/design.md` "Findings").
 *
 * Sample values arrive already masked from the backend (ADR-003); there is no unmask
 * control, so none is rendered.
 */

import { FileJson, FileText, Sheet, X } from "lucide-react";

import { Badge, Button } from "@/components/ui/primitives";
import { FINDING_LABEL, LEG_LABEL, SEVERITY_LABEL, SEVERITY_TONE } from "@/lib/display";
import type { Finding } from "@/lib/types";

export interface EvidencePanelProps {
  finding: Finding | null;
  onClose: () => void;
}

export function EvidencePanel({ finding, onClose }: EvidencePanelProps) {
  if (!finding) return null;
  const { evidence } = finding;

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/35" onClick={onClose} aria-hidden="true" />
      <aside
        className="fixed right-0 top-0 z-40 flex h-screen w-[30rem] max-w-[92vw] flex-col border-l bg-card shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={`Evidence for ${finding.finding_id}`}
      >
        <div className="flex items-start justify-between gap-2 border-b p-4">
          <div>
            <div className="mono text-xs text-muted-foreground">{finding.finding_id}</div>
            <h3 className="mt-0.5 text-sm font-semibold">{finding.title}</h3>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close evidence" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={SEVERITY_TONE[finding.severity]}>{SEVERITY_LABEL[finding.severity]}</Badge>
            <Badge tone="outline">{FINDING_LABEL[finding.type] ?? finding.type}</Badge>
            <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {LEG_LABEL[finding.leg] ?? finding.leg}
            </span>
          </div>

          <p className="text-xs leading-relaxed text-muted-foreground">{finding.detail}</p>

          {evidence.osl_text ? (
            <section>
              <h4 className="mb-1.5 flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                <FileText className="h-3.5 w-3.5" /> {evidence.osl_ref || "OSL"}
              </h4>
              <blockquote className="rounded-r-md border-l-[3px] border-primary bg-muted/50 px-3 py-2 text-xs leading-relaxed">
                {evidence.osl_text}
              </blockquote>
            </section>
          ) : null}

          {evidence.config_path ? (
            <section>
              <h4 className="mb-1.5 flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                <FileJson className="h-3.5 w-3.5" /> Config
              </h4>
              <pre className="mono overflow-x-auto rounded-md border bg-muted px-3 py-2 text-[0.72rem] leading-relaxed">
                {evidence.config_path}
                {evidence.config_value ? `\n${evidence.config_value}` : ""}
              </pre>
            </section>
          ) : null}

          {evidence.report_name ? (
            <section>
              <h4 className="mb-1.5 flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                <Sheet className="h-3.5 w-3.5" /> Report
              </h4>
              <div className="rounded-md border px-3 py-2 text-xs">
                <div className="mono text-[0.72rem]">
                  {evidence.report_name}
                  {evidence.report_sheet ? ` · ${evidence.report_sheet}` : ""}
                  {evidence.report_cell ? `!${evidence.report_cell}` : ""}
                </div>
                {evidence.report_value ? (
                  <div className="mt-1 font-semibold">{evidence.report_value}</div>
                ) : null}
              </div>
            </section>
          ) : null}

          {finding.verified ? (
            <p className="text-[0.7rem] text-muted-foreground">
              {finding.verify_agreed
                ? "A second opinion agreed with this finding."
                : "A second opinion disagreed; the finding was kept and marked for review."}
            </p>
          ) : null}
        </div>
      </aside>
    </>
  );
}

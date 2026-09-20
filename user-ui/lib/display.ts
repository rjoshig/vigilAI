/**
 * How domain values are shown: the tone a severity gets, the label a status reads as.
 * Kept out of components so the Runs list, the Review screen, and the stats page can
 * never disagree about what "needs_review" looks like.
 */

import type { ReviewStatus, RunStatus, Severity, Trace } from "@/lib/types";

/** The badge tone for each severity. */
export const SEVERITY_TONE: Record<Severity, "destructive" | "warn" | "info" | "muted"> = {
  high: "destructive",
  medium: "warn",
  low: "info",
  review: "muted",
};

/** The label for each severity. */
export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  review: "Review",
};

/** Worst first, which is the order every list uses. */
export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low", "review"];

/** The badge tone for each run status. */
export const STATUS_TONE: Record<
  RunStatus,
  "muted" | "info" | "warn" | "solid-success" | "destructive"
> = {
  draft: "muted",
  queued: "muted",
  running: "info",
  needs_review: "warn",
  finalized: "solid-success",
  failed: "destructive",
};

/** The label for each run status. */
export const STATUS_LABEL: Record<RunStatus, string> = {
  draft: "Draft",
  queued: "Queued",
  running: "Running",
  needs_review: "Needs review",
  finalized: "Finalized",
  failed: "Failed",
};

/** Whether a run is still moving, and so worth polling. */
export function isActive(status: RunStatus): boolean {
  return status === "queued" || status === "running";
}

/** The label for a review decision, as the reviewer chose it. */
export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  undecided: "Undecided",
  confirmed: "Not OK",
  false_positive: "OK — false positive",
  accepted_risk: "OK — accepted risk",
};

/**
 * Whether a decision counts as "OK" for the reviewer.
 *
 * "confirmed" means the reviewer agrees the finding is real, which is Not OK for the
 * delivery. The wording is inverted on purpose: the API records what is true about the
 * finding, the UI shows what it means for the order.
 */
export function isOk(status: ReviewStatus): boolean {
  return status === "false_positive" || status === "accepted_risk";
}

/** Severities on which Not OK must say why. Mirrors the API (Phase 6.11a). */
const NOTE_REQUIRED_FOR_NOT_OK: ReadonlySet<string> = new Set(["high", "review"]);

/**
 * Why a decision cannot be recorded as it stands, or "" when it is complete.
 *
 * The same rule runs in the API, which is what enforces it; this copy exists so the
 * reviewer is told before the request rather than by a rejection.
 */
export function decisionProblem(severity: string, status: ReviewStatus, note: string): string {
  if (note.trim()) return "";
  if (status === "accepted_risk") return "Accepting a risk needs a comment saying why.";
  if (status === "confirmed" && NOTE_REQUIRED_FOR_NOT_OK.has(severity)) {
    return `Not OK on a ${severity}-severity finding needs a comment saying what is wrong.`;
  }
  return "";
}

/** The matrix status for one requirement, from its trace and its findings. */
export type MatrixStatus = "match" | "mismatch" | "partial" | "missing" | "extra";

/** The badge tone for each matrix status. */
export const MATRIX_TONE: Record<MatrixStatus, "success" | "destructive" | "warn" | "info"> = {
  match: "success",
  mismatch: "destructive",
  partial: "warn",
  missing: "destructive",
  extra: "info",
};

/**
 * Decide how a requirement's row reads.
 *
 * The trace says whether anything implements the requirement; the findings say whether
 * what implements it agrees. Both are needed: a requirement can be traced and still
 * wrong, which is the most common case worth showing.
 */
export function matrixStatus(trace: Trace | null, findingTypes: string[]): MatrixStatus {
  if (!trace || trace.element_id === null || trace.verdict === "not_related") return "missing";
  if (trace.verdict === "contradicts") return "mismatch";
  if (findingTypes.some((t) => t === "extra_rule_in_config")) return "extra";
  if (
    findingTypes.some((t) =>
      [
        "value_mismatch",
        "operator_mismatch",
        "waterfall_order_mismatch",
        "report_violates_rule",
      ].includes(t)
    )
  ) {
    return "mismatch";
  }
  if (trace.verdict === "partial" || findingTypes.length > 0) return "partial";
  return "match";
}

/** Turn a finding type into the words the design doc uses for it. */
export const FINDING_LABEL: Record<string, string> = {
  rule_missing_in_config: "Rule missing in config",
  extra_rule_in_config: "Extra rule in config",
  value_mismatch: "Value mismatch",
  operator_mismatch: "Operator mismatch",
  waterfall_order_mismatch: "Waterfall order mismatch",
  report_violates_rule: "Report violates rule",
  count_does_not_reconcile: "Count does not reconcile",
  cross_report_disagreement: "Cross-report disagreement",
  judgment_failed: "Judgment check failed",
  profile_anomaly: "Profile anomaly",
  low_confidence_extraction: "Low-confidence extraction",
  could_not_evaluate: "Could not evaluate",
};

/** Which leg of the reconciliation a finding names. */
export const LEG_LABEL: Record<string, string> = {
  osl_config: "OSL ↔ config",
  config_reports: "config ↔ reports",
  osl_reports: "OSL ↔ reports",
};

/** Where a finding came from, in words a reviewer can act on (Phase 6.13b). */
export const ORIGIN_LABEL: Record<string, string> = {
  built_in: "From the OSL and the configuration",
  admin: "Administrator's rule",
  guide: "From a validation guide",
  meaning: "From the meaning map",
  learned: "Learned from an observation",
};

/** What became of an observation, to its author (Phase 6.13b). */
export const OUTCOME_LABEL: Record<string, string> = {
  waiting: "Waiting for an administrator to look at it",
  drafted: "The model has drafted a rule from it, for an administrator to approve",
  approved: "Approved: the rule runs in shadow, counted but shown to nobody yet",
  live: "Live: the rule produces findings on every run in its scope",
  disabled: "The rule was switched off; nothing in the training record is deleted",
  rejected: "Not taken forward",
};

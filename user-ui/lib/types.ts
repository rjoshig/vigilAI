/**
 * Domain types, mirroring the FastAPI wire models in `src/vigilai/api/schemas.py`.
 * Defined once here and imported everywhere, so a field only ever has one shape.
 */

/** Where a run is in its lifecycle. */
export type RunStatus = "draft" | "queued" | "running" | "needs_review" | "finalized" | "failed";

/** How serious a finding is. "review" means a person must look, not that it is wrong. */
export type Severity = "high" | "medium" | "low" | "review";

/** A reviewer's decision. */
export type ReviewStatus = "undecided" | "confirmed" | "false_positive" | "accepted_risk";

/** Which leg of the three-way reconciliation broke. */
export type Leg = "osl_config" | "config_reports" | "osl_reports";

/** The nine pipeline stages, in order. */
export const STAGES = [
  "s1_parse",
  "s2_extract",
  "s3_describe",
  "s4_trace",
  "s5_compare",
  "s6_reverse",
  "s7_reports",
  "s8_verify",
  "s9_summarize",
] as const;

export type StageName = (typeof STAGES)[number];

/** Human labels for the stage names, shown in progress and stats. */
export const STAGE_LABELS: Record<string, string> = {
  s1_parse: "Parse files",
  s2_extract: "Extract OSL requirements",
  s3_describe: "Describe config elements",
  s4_trace: "Trace requirement → config",
  s5_compare: "Compare values",
  s6_reverse: "Reverse pass",
  s7_reports: "Check reports",
  s8_verify: "Verify high severity",
  s9_summarize: "Summarize",
};

/** The report types the pipeline knows how to read. */
export const REPORT_KINDS = [
  "dirt",
  "field_distribution",
  "state_distribution",
  "score_distribution",
  "counts",
  "cross_tab",
  "billing",
] as const;

export type ReportKind = (typeof REPORT_KINDS)[number];

/** Human labels for the report types, shown on the upload form. */
export const REPORT_LABELS: Record<ReportKind, string> = {
  dirt: "DIRT",
  field_distribution: "Field distribution",
  state_distribution: "State distribution",
  score_distribution: "Score distribution",
  counts: "Counts / number flow",
  cross_tab: "Cross tab",
  billing: "Billing",
};

export interface StageInfo {
  stage: string;
  status: string;
  duration_ms: number;
  llm_calls: number;
  cache_hits: number;
  tokens: number;
  error: string;
}

export interface RunSummary {
  id: number;
  customer_name: string;
  order_number: string;
  configuration_id: string;
  status: RunStatus;
  current_stage: string;
  error: string;
  created_at: string;
  finished_at: string | null;
  high: number;
  medium: number;
  low: number;
  review: number;
  queue_position: number | null;
}

export interface RunDetail extends RunSummary {
  notes: string;
  run_date: string | null;
  rules_version: number;
  model_used: string;
  prompt_version: string;
  summary: string;
  top_issues: string[];
  rerun_reason: string;
  input_fingerprint: string;
  can_finalize: boolean;
  finalized: boolean;
  /** Whether this deployment can render a PDF at all (the optional [pdf] extra). */
  pdf_available: boolean;
  stages: StageInfo[];
  files: Record<string, string>;
}

export interface Evidence {
  osl_ref?: string;
  osl_text?: string;
  config_path?: string;
  config_value?: string;
  report_name?: string;
  report_sheet?: string;
  report_cell?: string;
  report_value?: string;
  sample_rows?: number[];
}

export interface Finding {
  id: number;
  finding_id: string;
  type: string;
  severity: Severity;
  title: string;
  detail: string;
  leg: Leg;
  rule_ref: string;
  element_ref: string;
  evidence: Evidence;
  rules_version: number;
  review_status: ReviewStatus;
  review_note: string;
  verified: boolean;
  verify_agreed: boolean | null;
}

export interface Rule {
  rule_id: string;
  source: string;
  req_type: string;
  summary: string;
  confidence: number;
  source_ref: string;
  source_text: string;
  rule: Record<string, unknown>;
}

export interface Trace {
  rule_id: string;
  element_id: string | null;
  verdict: "implemented" | "partial" | "contradicts" | "not_related";
  reason: string;
  confidence: number;
  by_code: boolean;
}

export interface ConfigElementOut {
  element_id: string;
  json_path: string;
  is_technical: boolean;
  description: string;
  rule: Record<string, unknown> | null;
}

export interface Requirements {
  rules: Rule[];
  traces: Trace[];
  elements: ConfigElementOut[];
  rules_version: number;
}

export interface RunStats {
  run_id: number;
  total_duration_ms: number;
  llm_calls: number;
  cache_hits: number;
  prompt_tokens: number;
  completion_tokens: number;
  stages: StageInfo[];
}

export interface ConfigSummary {
  id: number;
  configuration_id: string;
  version: number;
  customer_name: string;
  sha256: string;
  last_modified: string;
  created_at: string;
  run_count: number;
}

export interface ConfigDetail extends ConfigSummary {
  content: Record<string, unknown>;
}

export interface DuplicateRun {
  run_id: number;
  status: string;
  created_at: string;
  message: string;
}

export interface CreateRunResult {
  run_id: number | null;
  status: string;
  queue_position: number | null;
  duplicate: DuplicateRun | null;
}

export interface RecheckResult {
  run_id: number;
  rules_version: number;
  queued: boolean;
  findings: number;
}

export interface CloneResult {
  run_id: number;
  cloned_from: number;
  status: string;
}

/**
 * The traceability matrix as the review screen shows it: one row per requirement,
 * joining a rule to its trace and the element it points at.
 */
export interface MatrixRow {
  rule: Rule;
  trace: Trace | null;
  element: ConfigElementOut | null;
  status: "match" | "mismatch" | "partial" | "missing" | "extra";
  findings: Finding[];
}

export interface FinalizeResult {
  run_id: number;
  verdict: "ok" | "not_ok";
  html_sha256: string;
  pdf_available: boolean;
}

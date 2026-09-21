/**
 * Domain types, mirroring the FastAPI wire models in `src/greenlight_ai/api/schemas.py`.
 * Defined once here and imported everywhere, so a field only ever has one shape.
 */

/** Where a run is in its lifecycle. */
/**
 * A run's lifecycle. "held" means the artifacts disagree with what was submitted;
 * "cancelled" means the submitter took it back before it started (Phase 6.14j).
 * and somebody has to accept that before it starts (ADR-041); the files are
 * already stored, so nothing needs re-uploading.
 */
export type RunStatus =
  "draft" | "held" | "cancelled" | "queued" | "running" | "needs_review" | "finalized" | "failed";

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
  /** The credit date the delivery is cut as of (null when not given). */
  credit_date: string | null;
  status: RunStatus;
  current_stage: string;
  error: string;
  created_at: string;
  finished_at: string | null;
  /** Who submitted the run. The seeded placeholder's name while login is off (ADR-022). */
  submitted_by: string;
  /** The delivery programme's code, or empty when the submitter did not say. */
  scope: string;
  /** The programme's name, e.g. "Account Monitoring". */
  scope_label: string;
  high: number;
  medium: number;
  low: number;
  review: number;
  queue_position: number | null;
  /** When the purge may delete this run. A draft's window is much shorter. */
  expires_at?: string | null;
  /** The run this was cloned from, when it was one. */
  cloned_from?: number | null;
}

/** One artifact stored against a run, with its part and label (Phase 6.23c). */
export interface RunFileOut {
  id: number;
  kind: string;
  part: number;
  part_label: string;
  filename: string;
  size_bytes: number;
}

export interface RunDetail extends RunSummary {
  /**
   * The failure at length: stage, attempt and traceback. Only the run carries it —
   * the list has the one-line `error` and nothing more.
   */
  error_detail: string;
  notes: string;
  /** The credit date the delivery is cut as of; the tool checks the reports carry it. */
  rules_version: number;
  model_used: string;
  prompt_version: string;
  summary: string;
  top_issues: string[];
  rerun_reason: string;
  input_fingerprint: string;
  can_finalize: boolean;
  /** Why not, when can_finalize is false. Empty when the gate is satisfied. */
  finalize_blocked_by: string;
  finalized: boolean;
  /** Whether this deployment can render a PDF at all (the optional [pdf] extra). */
  pdf_available: boolean;
  stages: StageInfo[];
  files: Record<string, string>;
  /** The same artifacts as rows, with their parts and labels (Phase 6.23c). */
  files_detail?: RunFileOut[];
  /** Whether the submitter said suppressions were applied. */
  has_suppressions?: boolean;
  /** Anything else about the delivery the submitter wrote down. */
  delivery_notes?: string;
  /** Where the artifacts disagreed with the submission, accepted or not (ADR-041). */
  mismatches: ArtifactMismatch[];
  /**
   * The configuration notes in force when the run was submitted (ADR-024). Copied
   * onto the run so that what the model was told cannot change after the fact.
   */
  config_notes: string[];
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

/** One reader's view of a finding. They never see each other; code merges them. */
export interface LensOpinion {
  lens: string;
  answered: boolean;
  agreed?: boolean;
  reason?: string;
  confidence?: number;
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
  /** What each of stage 8's readers said, when several read it (Phase 6.11e). */
  lens_opinions?: LensOpinion[];
  /**
   * Where the finding came from (Phase 6.13b): `built_in` when code produced it from
   * the OSL and the configuration alone, else the origin of the rule behind it.
   */
  origin?: FindingOrigin;
  rule_name?: string;
  rule_summary?: string;
}

export type FindingOrigin = "built_in" | "admin" | "guide" | "meaning" | "learned";

/** One rule that touched a run (Phase 6.13b). */
export interface RunRule {
  rule_ref: string;
  kind: string;
  name: string;
  summary: string;
  origin: FindingOrigin;
  state: string;
  findings: number;
  shadow: boolean;
}

export interface RunRules {
  applied: RunRule[];
  /** Rules that ran in shadow on this run: named, and nothing more. */
  running_silently: RunRule[];
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
  /** What this run cost at the configured rate (Phase 6.21d). Zero when nobody
   * has set one, in which case the screen shows tokens and no currency. */
  cost: number;
  currency: string;
  rate_per_million: number;
  /** The per-run token ceiling — the only hard stop in the product — so a run can
   * say how close it came rather than only reporting that it was stopped. */
  budget_tokens: number;
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
  /** Who ran the submission that captured this config version (ADR-022). */
  created_by: string;
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

/**
 * One field where the artifacts disagree with what was submitted (ADR-041).
 *
 * `kind` is "near" when the two are the same once punctuation and company suffixes
 * are removed, and "different" otherwise. A near match is still shown: it is usually
 * the same customer and occasionally is not.
 */
export interface ArtifactMismatch {
  id: number;
  field: string;
  /** A short label for the field, so the screen need not know the vocabulary. */
  label: string;
  submitted: string;
  declared: string;
  kind: "near" | "different";
  source: string;
  reason: string;
  accepted_at: string | null;
  accepted_by: string;
}

export interface CreateRunResult {
  run_id: number | null;
  status: string;
  queue_position: number | null;
  duplicate: DuplicateRun | null;
  /**
   * Non-empty when `status` is "held": the artifacts disagree with what was typed.
   * The files are already stored, so accepting costs a reason and a click.
   */
  mismatches: ArtifactMismatch[];
}

export interface AcceptMismatchesResult {
  run_id: number;
  status: string;
  accepted: number;
  queue_position: number | null;
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

/** One upload slot the new-run form should draw, from the admin catalog (ADR-020). */
export interface ArtifactSlot {
  key: string;
  label: string;
  kind: "osl" | "config" | "report";
  description: string;
  is_required: boolean;
  accept: string;
}

/** One delivery programme a run can belong to. */
export interface ScopeOption {
  code: string;
  label: string;
  description: string;
}

/** Everything the new-run form needs in order to draw itself. */
export interface NewRunOptions {
  artifacts: ArtifactSlot[];
  scopes: ScopeOption[];
}

/** Which of the two independent login switches are on (ADR-022). Both ship false. */
export interface AuthConfig {
  admin_auth: boolean;
  user_auth: boolean;
}

/** The current user. There is always one: the placeholder while login is off. */
export interface CurrentUser {
  id: number;
  name: string;
  email: string;
  /** Every role held, weakest first (ADR-049). */
  roles: string[];
  /**
   * What this person may do, as the API resolved it. The app never derives this from
   * the roles: the matrix lives on the server, and a console that reimplemented it
   * would disagree with the API the first time a grant moved — by offering a screen
   * that then refuses.
   */
  capabilities: string[];
  is_admin: boolean;
  is_placeholder: boolean;
  must_change_password: boolean;
}

/* ------------------------------------------- Workbook type detection (6.1d) */

/** One artifact type an uploaded workbook might be, with its score. */
export interface DetectedCandidate {
  key: string;
  label: string;
  score: number;
}

/** What one tab of a workbook looks like, scored on its own. */
export interface DetectedSheet {
  sheet: string;
  verdict: DetectionVerdict;
  reason: string;
  key: string | null;
  label: string | null;
  score: number;
}

/**
 * How sure the detector is. "I am not sure" has to be representable, because a wrong
 * silent assignment is worse than a question.
 */
export type DetectionVerdict = "confident" | "reasoned" | "ambiguous" | "unknown";

/** What `POST /runs/detect-type` returns. It stores nothing. */
export interface TypeDetection {
  verdict: DetectionVerdict;
  reason: string;
  key: string | null;
  label: string | null;
  score: number;
  candidates: DetectedCandidate[];
  sheets: DetectedSheet[];
}

/* ------------------------------------------------- The training loop (ADR-021) */

/** Whether Train AI mode is on. Off by default; nothing about training shows when off. */
export interface TrainingConfig {
  enabled: boolean;
}

export type AnchorKind =
  "report_cell" | "report_field" | "osl_section" | "config_path" | "finding" | "rule" | "run";

/**
 * What an observation points at. The anchor is what makes reliable synthesis possible;
 * the sentence alone is a guess.
 */
export interface Anchor {
  kind: AnchorKind;
  artifact: string;
  sheet: string;
  cell: string;
  field: string;
  reference: string;
  value: string;
}

/** What kind of thing the reviewer is telling the tool. */
export type ObservationKind =
  "reconciliation" | "field_constraint" | "correction" | "note" | "config_note";

/** How wide a rule drawn from this observation should apply. */
export type ObservationScope = "global" | "customer" | "programme";

/** Where an observation can be in its lifecycle. It never runs; only an approved rule does. */
export type ObservationStatus = "new" | "synthesized" | "rejected";

/** The body `POST /observations` and `PATCH /observations/{id}` both take. */
export interface ObservationInput {
  kind: ObservationKind;
  anchors: Anchor[];
  statement: string;
  expectation: string;
  severity_hint: Severity;
  scope_hint: ObservationScope;
  run_id?: number | null;
  finding_id?: number | null;
}

/** One earlier wording of a configuration note, kept when the note is edited. */
export interface NoteRevision {
  version: number;
  statement: string;
  at: string;
  by: string;
}

/**
 * The body `POST /configs/{configuration_id}/notes` and `PATCH /config-notes/{id}`
 * both take. A note is guidance, so it carries no anchor and no expectation.
 */
export interface ConfigNoteInput {
  statement: string;
  severity_hint?: Severity;
}

/** A stored observation, as its author sees it. */
export interface Observation extends ObservationInput {
  id: number;
  author: string;
  status: ObservationStatus;
  /** On a rejection, the administrator's reason, in their words. */
  status_note: string;
  candidate_id: number | null;
  customer_name: string;
  scope_code: string;
  version: number;
  /** Whether the author may still edit it. False once an administrator picks it up. */
  editable: boolean;
  created_at: string;
  synthesized_at: string | null;
  /** Set on a `config_note`: the ETL configuration the note follows (ADR-024). */
  configuration_id: string;
  /** A note is switched off rather than deleted, so the record of it survives. */
  is_active: boolean;
  /** Earlier wordings of a note, oldest first. Empty until it has been edited. */
  revisions: NoteRevision[];
  /**
   * Active rules that already cover what this points at (Phase 6.1e).
   *
   * Returned when the observation is saved, so the author sees it while they can
   * still reconsider rather than hearing weeks later through an administrator.
   */
  covered_by?: CoveringRule[];
  /**
   * What became of it, read from the rule tables (Phase 6.13b): waiting · drafted ·
   * approved (in shadow) · live · disabled · rejected.
   */
  outcome: ObservationOutcome;
  outcome_note: string;
  rule_ref: string;
  rule_name: string;
  rule_summary: string;
  rule_state: string;
}

export type ObservationOutcome =
  "waiting" | "drafted" | "approved" | "live" | "disabled" | "rejected";

/** One populated cell of a sample, addressable the way a named value addresses it. */
export interface CellPreview {
  cell: string;
  value: string;
  label: string;
  row: number;
  column: number;
}

/** One sheet of a sample, or one OSL section, or one configuration block. */
export interface SheetPreview {
  name: string;
  rows: number;
  columns: number;
  cells: CellPreview[];
}

/** What a sample contains, for someone deciding what to point at (Phase 6.1e). */
export interface SamplePreview {
  sample_id: number;
  filename: string;
  sheets: SheetPreview[];
}

/** One sample a reviewer can explore. */
export interface ExploreSample {
  id: number;
  label: string;
  filename: string;
  sheets: string[];
  notes: string;
  scope_code: string;
}

/** An artifact type and the samples stored for it. */
export interface ExploreArtifact {
  key: string;
  label: string;
  /** "osl", "config", or a report kind. It decides what a preview looks like. */
  kind: string;
  samples: ExploreSample[];
}

/** An active rule that already covers what an observation points at (Phase 6.1e). */
export interface CoveringRule {
  kind: string;
  id: number;
  name: string;
  summary: string;
  scope: string;
  state: string;
  /** Whether the statement reads as the opposite of this rule. A hint, not a verdict. */
  contradicts: boolean;
}

/** A finding as the drift panel refers to it (ADR-030). */
export interface DriftFinding {
  finding_id: string;
  type: string;
  severity: Severity;
  title: string;
  review_status: string;
}

export interface DriftRequirement {
  rule_id: string;
  req_type: string;
  source_ref: string;
  change: "added" | "removed" | "changed";
  before: string;
  after: string;
}

export interface DriftConfigChange {
  path: string;
  change: "added" | "removed" | "changed";
  before: string;
  after: string;
}

/** What changed since the previous finalized run of the same configuration. */
export interface Drift {
  previous_run_id: number | null;
  previous_finished_at: string;
  previous_verdict: string;
  reason: string;
  new: DriftFinding[];
  resolved: DriftFinding[];
  carried_not_ok: DriftFinding[];
  requirements: DriftRequirement[];
  config: DriftConfigChange[];
  previous_config_version: number | null;
  config_version: number | null;
  /** OSL references a report evidenced last time and evidences no longer. */
  newly_unchecked: string[];
}

/** What happened to one requirement: was it actually checked? (Phase 6.11c) */
export type CoverageState = "checked" | "traced_unchecked" | "untraced" | "manual";

export interface RequirementCoverage {
  rule_id: string;
  req_type: string;
  state: CoverageState;
  osl_ref: string;
  summary: string;
  reason: string;
  acknowledged: boolean;
  acknowledged_by: string;
  acknowledgement_note: string;
}

export interface ReportCoverage {
  kind: string;
  checks_applied: number;
}

export interface UnevaluatedCheck {
  finding_id: string;
  title: string;
  acknowledged: boolean;
  acknowledged_by: string;
  acknowledgement_note: string;
}

export interface Coverage {
  requirements: RequirementCoverage[];
  reports: ReportCoverage[];
  unevaluated: UnevaluatedCheck[];
  notices: string[];
  counts: Record<string, number>;
  /** Requirement ids and finding ids still waiting for an acknowledgement. */
  outstanding: string[];
  reason: string;
}
